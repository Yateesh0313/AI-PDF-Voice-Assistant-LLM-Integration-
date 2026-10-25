"""
LLM & RAG service — per-user retriever management and answer generation.
Includes dynamic model discovery, automatic model fallback, retry logic,
and graceful error recovery.
"""
import os
import logging
from typing import Dict, List, Optional

from langchain_openai import ChatOpenAI
from langchain_community.document_loaders import PDFPlumberLoader
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

from config import (
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TEMPERATURE,
    EMBEDDING_MODEL, LLM_REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

# ── Lazy-initialize embeddings ────────────────────────
_embeddings = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        logger.info("Initializing embedding model: %s", EMBEDDING_MODEL)
        # FastEmbed uses ONNX — no PyTorch needed, ~100 MB RAM
        _embeddings = FastEmbedEmbeddings(model_name=EMBEDDING_MODEL)
        logger.info("Embedding model loaded successfully.")
    return _embeddings


# ── Dynamic Model Discovery & Fallback ────────────────
_active_model: Optional[str] = None
_discovered_models: Optional[List[str]] = None

_DEFAULT_FALLBACKS = [
    LLM_MODEL,
    "llama-3.3-70b-versatile",
    "llama3-8b-8192",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]


def _discover_models() -> List[str]:
    """Query /models endpoint to find valid models for this API key."""
    global _discovered_models
    if _discovered_models is not None:
        return _discovered_models

    if not LLM_API_KEY or LLM_API_KEY == "lm-studio":
        return _DEFAULT_FALLBACKS

    try:
        import httpx
        resp = httpx.get(
            f"{LLM_BASE_URL}/models",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            timeout=8.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            remote_models = [m["id"] for m in data.get("data", [])]
            logger.info("Found %d models on %s", len(remote_models), LLM_BASE_URL)

            # Filter for text chat models (exclude whisper, embedding, guardrails)
            chat_models = [
                m for m in remote_models
                if not any(x in m.lower() for x in ["whisper", "embed", "guard", "moderation", "audio"])
            ]
            if chat_models:
                order = []
                # Keep configured model first if present
                if LLM_MODEL in chat_models:
                    order.append(LLM_MODEL)
                for pref in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-8b-8192", "mixtral-8x7b-32768"]:
                    if pref in chat_models and pref not in order:
                        order.append(pref)
                for m in chat_models:
                    if m not in order:
                        order.append(m)
                _discovered_models = order
                logger.info("Candidate models order: %s", _discovered_models[:5])
                return _discovered_models
    except Exception as e:
        logger.warning("Could not auto-discover models from %s: %s", LLM_BASE_URL, e)

    return _DEFAULT_FALLBACKS


def _create_llm(model_name: str):
    return ChatOpenAI(
        model=model_name,
        temperature=LLM_TEMPERATURE,
        openai_api_base=LLM_BASE_URL,
        openai_api_key=LLM_API_KEY,
        request_timeout=LLM_REQUEST_TIMEOUT,
        max_retries=1,
    )


def _invoke_with_fallback(invoke_fn):
    """
    Execute invoke_fn(llm), automatically trying fallback models if the model is not found or unsupported.
    Caches the successful model for subsequent requests.
    """
    global _active_model

    candidates = []
    if _active_model:
        candidates.append(_active_model)
    for m in _discover_models():
        if m not in candidates:
            candidates.append(m)

    last_error = None
    for model_name in candidates:
        try:
            llm = _create_llm(model_name)
            result = invoke_fn(llm)
            if _active_model != model_name:
                logger.info("Model '%s' succeeded! Caching as active model.", model_name)
                _active_model = model_name
            return result
        except Exception as e:
            last_error = e
            err_lower = str(e).lower()
            # If the error is model_not_found / does not exist / 404, try next model
            if any(k in err_lower for k in ["model_not_found", "does not exist", "not found", "404", "unknown_url", "not supported", "decommissioned"]):
                logger.warning("Model '%s' failed (%s). Trying next candidate...", model_name, e)
                continue
            # For auth errors, rate limits, timeouts, re-raise immediately
            raise e

    raise last_error


# ── Per-user retriever cache ──────────────────────────
_user_retrievers: Dict[int, object] = {}


def build_retriever(user_id: int, pdf_paths: List[str]):
    """
    (Re)build the FAISS retriever for a user from their PDF files.
    Called after upload or delete.
    """
    all_chunks = []
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=200)

    for path in pdf_paths:
        if os.path.exists(path):
            try:
                docs = PDFPlumberLoader(path).load()
                all_chunks.extend(splitter.split_documents(docs))
            except Exception as e:
                logger.error("Failed to load PDF %s: %s", path, e)
                continue

    if all_chunks:
        try:
            vs = FAISS.from_documents(all_chunks, _get_embeddings())
            _user_retrievers[user_id] = vs.as_retriever(search_kwargs={"k": 3})
            logger.info("Built retriever for user %d with %d chunks from %d PDFs",
                        user_id, len(all_chunks), len(pdf_paths))
        except Exception as e:
            logger.error("Failed to build FAISS index for user %d: %s", user_id, e)
            _user_retrievers.pop(user_id, None)
    else:
        _user_retrievers.pop(user_id, None)


def get_answer(question: str, user_id: int) -> tuple[str, str]:
    """
    Answer a question using RAG (if PDF indexed) or direct LLM.
    Returns (answer_text, source) where source is "pdf" or "general".
    Includes dynamic model fallback so the chat never fails from deprecated/unavailable models.
    """
    retriever = _user_retrievers.get(user_id)

    try:
        if retriever is None:
            resp = _invoke_with_fallback(lambda llm: llm.invoke(question))
            return resp.content, "general"

        prompt = ChatPromptTemplate.from_template("""
Use ONLY the PDF context to answer.
If answer not present, reply exactly: NO_DATA

Context:
{context}

Question:
{question}
""")

        def _run_rag(llm):
            chain = (
                {"context": retriever, "question": RunnablePassthrough()}
                | prompt
                | llm
                | StrOutputParser()
            )
            return chain.invoke(question)

        answer = _invoke_with_fallback(_run_rag)

        if "NO_DATA" in answer:
            resp = _invoke_with_fallback(lambda llm: llm.invoke(question))
            return resp.content, "general"

        return answer, "pdf"

    except Exception as e:
        logger.error("LLM/RAG error for user %d: %s", user_id, e)
        error_msg = str(e).lower()
        if LLM_API_KEY == "lm-studio" or "api key" in error_msg or "authentication" in error_msg or "401" in error_msg:
            return "⚠️ AI API key not configured or invalid. Please add your Groq API key as OPENAI_API_KEY or GROQ_API_KEY in the Render dashboard environment variables.", "general"
        elif "rate limit" in error_msg or "429" in error_msg:
            return "⚠️ The AI service is rate-limited. Please wait a moment and try again.", "general"
        elif "timeout" in error_msg or "timed out" in error_msg:
            return "⚠️ The AI service took too long to respond. Please try again.", "general"
        else:
            return f"⚠️ Could not generate an answer: {str(e)}", "general"

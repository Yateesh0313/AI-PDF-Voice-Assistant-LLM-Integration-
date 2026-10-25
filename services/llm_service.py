"""
LLM & RAG service — per-user retriever management and answer generation.
Includes retry logic, timeout handling, and graceful error recovery.
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

# ── Lazy-initialize LLM & embeddings (on first use) ───
# Avoids blocking server startup — Render times out if port isn't bound quickly.
_llm = None
_embeddings = None


def _get_llm():
    global _llm
    if _llm is None:
        logger.info("Initializing LLM: model=%s, base_url=%s", LLM_MODEL, LLM_BASE_URL)
        _llm = ChatOpenAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            openai_api_base=LLM_BASE_URL,
            openai_api_key=LLM_API_KEY,
            request_timeout=LLM_REQUEST_TIMEOUT,
            max_retries=2,
        )
    return _llm


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        logger.info("Initializing embedding model: %s", EMBEDDING_MODEL)
        # FastEmbed uses ONNX — no PyTorch needed, ~100 MB RAM
        _embeddings = FastEmbedEmbeddings(model_name=EMBEDDING_MODEL)
        logger.info("Embedding model loaded successfully.")
    return _embeddings


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
    Includes error handling so the chat never fully crashes.
    """
    retriever = _user_retrievers.get(user_id)

    try:
        if retriever is None:
            return _get_llm().invoke(question).content, "general"

        prompt = ChatPromptTemplate.from_template("""
    Use ONLY the PDF context to answer.
    If answer not present, reply exactly: NO_DATA

    Context:
    {context}

    Question:
    {question}
    """)

        chain = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt
            | _get_llm()
            | StrOutputParser()
        )

        answer = chain.invoke(question)

        if "NO_DATA" in answer:
            return _get_llm().invoke(question).content, "general"

        return answer, "pdf"

    except Exception as e:
        logger.error("LLM/RAG error for user %d: %s", user_id, e)
        if LLM_API_KEY == "lm-studio" or "api key" in error_msg or "authentication" in error_msg or "401" in error_msg:
            return "⚠️ AI API key not configured or invalid. Please add your Groq API key as OPENAI_API_KEY or GROQ_API_KEY in the Render dashboard environment variables.", "general"
        elif "not found" in error_msg or "notfound" in error_msg or "404" in error_msg or "unknown request url" in error_msg:
            return "⚠️ AI model or endpoint not found. Please verify OPENAI_API_BASE is set to https://api.groq.com/openai/v1 and LLM_MODEL is set to llama-3.1-8b-instant.", "general"
        elif "rate limit" in error_msg or "429" in error_msg:
            return "⚠️ The AI service is rate-limited. Please wait a moment and try again.", "general"
        elif "timeout" in error_msg or "timed out" in error_msg:
            return "⚠️ The AI service took too long to respond. Please try again.", "general"
        else:
            return f"⚠️ Could not generate an answer: {str(e)}", "general"

"""
LLM & RAG service — per-user retriever management and answer generation.
"""
import os
from typing import Dict, List, Optional

from langchain_openai import ChatOpenAI
from langchain_community.document_loaders import PDFPlumberLoader
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

from config import (
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TEMPERATURE, EMBEDDING_MODEL
)

# ── Lazy-initialize LLM & embeddings (on first use) ───
# Avoids blocking server startup — Render times out if port isn't bound quickly.
_llm = None
_embeddings = None

def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            openai_api_base=LLM_BASE_URL,
            openai_api_key=LLM_API_KEY,
        )
    return _llm

def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
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
            docs = PDFPlumberLoader(path).load()
            all_chunks.extend(splitter.split_documents(docs))

    if all_chunks:
        vs = FAISS.from_documents(all_chunks, _get_embeddings())
        _user_retrievers[user_id] = vs.as_retriever(search_kwargs={"k": 3})
    else:
        _user_retrievers.pop(user_id, None)


def get_answer(question: str, user_id: int) -> tuple[str, str]:
    """
    Answer a question using RAG (if PDF indexed) or direct LLM.
    Returns (answer_text, source) where source is "pdf" or "general".
    """
    retriever = _user_retrievers.get(user_id)

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

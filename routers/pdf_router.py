"""
PDF router — upload, list, and delete PDF documents (per-user).
"""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from models import User, PDFDocument
from auth import get_current_user
from config import UPLOAD_DIR
from services.llm_service import build_retriever

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


def _user_pdf_paths(user_id: int, db: Session) -> list[str]:
    """Return absolute paths for all of a user's PDFs."""
    pdfs = db.query(PDFDocument).filter(PDFDocument.user_id == user_id).all()
    return [str(UPLOAD_DIR / p.filename) for p in pdfs]


@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    stored_name = f"{uuid.uuid4().hex}.pdf"
    dest = UPLOAD_DIR / stored_name

    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    # Count pages
    from langchain_community.document_loaders import PDFPlumberLoader
    pages = len(PDFPlumberLoader(str(dest)).load())

    pdf_doc = PDFDocument(
        user_id=user.id,
        filename=stored_name,
        original_name=file.filename,
        page_count=pages,
    )
    db.add(pdf_doc)
    db.commit()
    db.refresh(pdf_doc)

    # Rebuild retriever with all user PDFs
    build_retriever(user.id, _user_pdf_paths(user.id, db))

    return {
        "id": pdf_doc.id,
        "original_name": pdf_doc.original_name,
        "page_count": pdf_doc.page_count,
        "message": "PDF uploaded and indexed successfully",
    }


@router.get("/list")
def list_pdfs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pdfs = (
        db.query(PDFDocument)
        .filter(PDFDocument.user_id == user.id)
        .order_by(PDFDocument.created_at.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "original_name": p.original_name,
            "page_count": p.page_count,
            "created_at": p.created_at.isoformat(),
        }
        for p in pdfs
    ]


@router.delete("/{pdf_id}")
def delete_pdf(pdf_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pdf = db.query(PDFDocument).filter(
        PDFDocument.id == pdf_id, PDFDocument.user_id == user.id
    ).first()
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF not found")

    # Remove file
    file_path = UPLOAD_DIR / pdf.filename
    if file_path.exists():
        os.remove(file_path)

    db.delete(pdf)
    db.commit()

    # Rebuild retriever without deleted PDF
    build_retriever(user.id, _user_pdf_paths(user.id, db))

    return {"ok": True}

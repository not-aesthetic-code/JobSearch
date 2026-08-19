"""The user's profile: one stored resume, which every pipeline run matches
against. Accepts markdown/plain text, or a PDF whose text layer we extract
server-side. PDFs arrive as a raw body rather than multipart — there is exactly
one field, so multipart would only add a dependency."""

import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.auth import RequireServiceKey
from jobsearch.database.models import Resume
from jobsearch.database.session import get_session
from jobsearch.services.pipeline import get_latest_resume, get_or_create_local_user, upsert_resume

router = APIRouter(dependencies=[RequireServiceKey], tags=["Profile"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

MIN_RESUME_CHARS = 50  # same floor the pipeline enforces — below this there is nothing to extract from
MAX_PDF_BYTES = 10 * 1024 * 1024


class ResumeIn(BaseModel):
    text: str = Field(min_length=MIN_RESUME_CHARS, description="Resume as markdown or plain text")


class ResumeOut(BaseModel):
    text: str
    keywords: list[str] | None
    updated_at: datetime


def pdf_to_text(data: bytes) -> str:
    """Text layer only. A scanned CV has none, and we say so rather than storing
    an empty resume that would silently produce an empty shortlist.
    ponytail: no OCR — add one if scanned CVs actually turn up."""
    from pypdf import PdfReader

    try:
        pages = PdfReader(io.BytesIO(data)).pages
        text = "\n\n".join(page.extract_text() or "" for page in pages).strip()
    except Exception as exc:  # noqa: BLE001 — any parse failure means the same thing to the caller
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read that PDF ({type(exc).__name__})",
        ) from exc

    if len(text) < MIN_RESUME_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That PDF has no text layer (scan or image-only) — paste the resume as text instead",
        )
    return text


def _to_out(resume: Resume) -> ResumeOut:
    return ResumeOut(text=resume.raw_text, keywords=resume.keywords, updated_at=resume.created_at)


async def _save(session: AsyncSession, text: str) -> ResumeOut:
    user = await get_or_create_local_user(session)
    return _to_out(await upsert_resume(session, user.id, text))


@router.get("/profile/resume")
async def read_resume(session: SessionDep) -> ResumeOut | None:
    """The stored resume, or null if the profile is still empty."""
    user = await get_or_create_local_user(session)
    resume = await get_latest_resume(session, user.id)
    return None if resume is None else _to_out(resume)


@router.put("/profile/resume")
async def put_resume(payload: ResumeIn, session: SessionDep) -> ResumeOut:
    return await _save(session, payload.text.strip())


@router.put("/profile/resume/pdf")
async def put_resume_pdf(request: Request, session: SessionDep) -> ResumeOut:
    """Raw `application/pdf` body — the extracted text becomes the stored resume."""
    data = await request.body()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"PDF is larger than {MAX_PDF_BYTES // 1024 // 1024} MB",
        )
    return await _save(session, pdf_to_text(data))

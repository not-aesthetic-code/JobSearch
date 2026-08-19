"""No DB, no network: just the PDF -> text step and its two rejection paths."""

import io

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter

from jobsearch.endpoints.profile import pdf_to_text


def _blank_pdf() -> bytes:
    """A valid PDF with no text layer — what a scanned CV looks like to pypdf."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_without_text_layer_is_rejected():
    with pytest.raises(HTTPException) as exc:
        pdf_to_text(_blank_pdf())
    assert exc.value.status_code == 400
    assert "no text layer" in exc.value.detail


def test_non_pdf_bytes_are_rejected():
    with pytest.raises(HTTPException) as exc:
        pdf_to_text(b"this is not a pdf at all")
    assert exc.value.status_code == 400

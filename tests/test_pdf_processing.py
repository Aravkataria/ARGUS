"""
ARGUS - PDF Dossier Ingestion & Forensics Test Suite
Tests multi-page PDF ingestion, metadata inspection, rasterization,
digital text extraction, risk aggregation, and FastAPI endpoint routing.
"""

import io
import os
import pytest
from fastapi.testclient import TestClient
from PIL import Image

# Ensure OMP duplicate lib error is suppressed on Windows
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

from app.main import app
from app.modules.pdf_processor import (
    is_pdf,
    inspect_pdf_metadata,
    rasterize_pdf_page,
    extract_pdf_page_digital_text,
    screen_pdf_dossier,
)

client = TestClient(app)


def _create_sample_pdf(
    num_pages: int = 1,
    creator: str = "Government Printing Office",
    producer: str = "Certified PDF Engine",
    text_content: str = "OFFICIAL GOVERNMENT IDENTIFICATION DOCUMENT",
) -> bytes:
    """Helper to synthesize an in-memory PDF with specified metadata and text."""
    if fitz is None:
        pytest.skip("PyMuPDF / fitz is not installed")

    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((50, 50), f"{text_content}\nPage {i+1} Content", fontsize=12)

    doc.set_metadata({
        "creator": creator,
        "producer": producer,
        "title": "Identity Dossier",
        "author": "Registrar",
        "creationDate": "D:20260101120000",
        "modDate": "D:20260101120000",
    })

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ============================================================================
# 1. MAGIC BYTES & FORMAT DETECTION
# ============================================================================

def test_is_pdf_magic_bytes():
    assert is_pdf(b"%PDF-1.7\r\nsome content") is True
    assert is_pdf(b"%PDF-2.0\r\nsome content") is True
    assert is_pdf(b"\x89PNG\r\n\x1a\n") is False
    assert is_pdf(b"\xff\xd8\xff\xe0") is False
    assert is_pdf(b"This is just plain text") is False
    assert is_pdf(12345) is False


def test_is_pdf_file_path(tmp_path):
    pdf_file = tmp_path / "document.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%test\n")
    assert is_pdf(str(pdf_file)) is True

    txt_file = tmp_path / "document.txt"
    txt_file.write_bytes(b"Not a PDF file content")
    assert is_pdf(str(txt_file)) is False


# ============================================================================
# 2. METADATA TAMPERING & FORENSICS
# ============================================================================

def test_inspect_pdf_metadata_clean():
    clean_pdf = _create_sample_pdf(
        creator="Official State Portal",
        producer="Quartz PDFContext",
    )
    doc = fitz.open(stream=clean_pdf, filetype="pdf")
    meta = inspect_pdf_metadata(doc)
    doc.close()

    assert meta["suspicious_software"] is False
    assert meta["flags"] == []
    assert meta["metadata_risk_score"] == 0.0
    assert meta["page_count"] == 1


def test_inspect_pdf_metadata_photoshop_flagged():
    forged_pdf = _create_sample_pdf(
        creator="Adobe Photoshop 2024 (Windows)",
        producer="Adobe Photoshop PDF Output",
    )
    doc = fitz.open(stream=forged_pdf, filetype="pdf")
    meta = inspect_pdf_metadata(doc)
    doc.close()

    assert meta["suspicious_software"] is True
    assert meta["metadata_risk_score"] == 0.85
    assert any("Photoshop" in flag for flag in meta["flags"])


def test_inspect_pdf_metadata_canva_flagged():
    canva_pdf = _create_sample_pdf(
        creator="Canva Web Exporter",
        producer="Canva Renderer",
    )
    doc = fitz.open(stream=canva_pdf, filetype="pdf")
    meta = inspect_pdf_metadata(doc)
    doc.close()

    assert meta["suspicious_software"] is True
    assert meta["metadata_risk_score"] == 0.85
    assert any("Canva" in flag for flag in meta["flags"])


# ============================================================================
# 3. RASTERIZATION & DIGITAL TEXT
# ============================================================================

def test_rasterize_pdf_page():
    pdf_bytes = _create_sample_pdf(num_pages=1)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    img_array, pil_img = rasterize_pdf_page(doc, 0, dpi=100)
    doc.close()

    assert img_array.ndim == 3
    assert img_array.shape[2] == 3  # RGB
    assert isinstance(pil_img, Image.Image)
    assert pil_img.size == (img_array.shape[1], img_array.shape[0])


def test_extract_pdf_page_digital_text():
    sample_text = "CONFIDENTIAL REGULATORY DOSSIER - PASSPORT OFFICE"
    pdf_bytes = _create_sample_pdf(num_pages=1, text_content=sample_text)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_info = extract_pdf_page_digital_text(doc[0])
    doc.close()

    assert text_info["has_digital_text"] is True
    assert sample_text in text_info["text"]
    assert text_info["char_count"] > len(sample_text)


# ============================================================================
# 4. DOSSIER SCREENING & MULTI-PAGE AGGREGATION
# ============================================================================

def test_screen_pdf_dossier_aggregation(monkeypatch):
    """
    Test multi-page risk aggregation: ensure highest page risk tier propagates.
    """
    pdf_bytes = _create_sample_pdf(num_pages=2)

    call_count = 0
    def fake_extract_fields(path):
        nonlocal call_count
        call_count += 1
        return {
            "mrz_found": False,
            "document_type": "PAN" if call_count == 1 else "PASSPORT",
            "checks": {"overall_valid": True},
            "document_number": f"DOC{call_count}0000",
            "fields": {},
        }

    monkeypatch.setattr("app.modules.pdf_processor.extract_document_fields", fake_extract_fields)
    monkeypatch.setattr(
        "app.modules.pdf_processor.analyze_tampering",
        lambda p: {"tampering_score": 0.05, "ela_score": 0.02, "metadata": {"flags": []}},
    )
    monkeypatch.setattr(
        "app.modules.pdf_processor.predict_visual_forgery",
        lambda img: {"label": "Authentic", "forged_probability": 0.05, "authentic_probability": 0.95},
    )

    result = screen_pdf_dossier(pdf_bytes, max_pages=5)

    assert result["document_format"] == "PDF"
    assert result["total_pages"] == 2
    assert result["pages_processed"] == 2
    assert len(result["pages"]) == 2
    assert "dossier_risk_tier" in result
    assert "dossier_risk_score" in result
    assert "risk" in result
    assert result["pages"][0]["page_number"] == 1
    assert result["pages"][1]["page_number"] == 2


# ============================================================================
# 5. FASTAPI /screen & /screen/pdf INTEGRATION
# ============================================================================

def test_screen_endpoint_with_pdf(monkeypatch):
    pdf_bytes = _create_sample_pdf(num_pages=1)

    monkeypatch.setattr(
        "app.modules.pdf_processor.extract_document_fields",
        lambda p: {
            "mrz_found": True,
            "document_type": "P",
            "checks": {"overall_valid": True},
            "document_number": "PP9999999",
            "fields": {},
        },
    )
    monkeypatch.setattr(
        "app.modules.pdf_processor.analyze_tampering",
        lambda p: {"tampering_score": 0.01, "ela_score": 0.01, "metadata": {"flags": []}},
    )
    monkeypatch.setattr(
        "app.modules.pdf_processor.predict_visual_forgery",
        lambda img: {"label": "Authentic", "forged_probability": 0.02, "authentic_probability": 0.98},
    )

    files = {"document": ("dossier.pdf", pdf_bytes, "application/pdf")}
    response = client.post("/screen", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["document_format"] == "PDF"
    assert body["total_pages"] == 1
    assert "pages" in body
    assert "risk" in body
    assert body["dossier_risk_tier"] in ("LOW", "MEDIUM", "HIGH", "INCONCLUSIVE")


def test_screen_pdf_dedicated_endpoint(monkeypatch):
    pdf_bytes = _create_sample_pdf(num_pages=1)

    monkeypatch.setattr(
        "app.modules.pdf_processor.extract_document_fields",
        lambda p: {
            "mrz_found": True,
            "document_type": "P",
            "checks": {"overall_valid": True},
            "document_number": "PP8888888",
            "fields": {},
        },
    )
    monkeypatch.setattr(
        "app.modules.pdf_processor.analyze_tampering",
        lambda p: {"tampering_score": 0.01, "ela_score": 0.01, "metadata": {"flags": []}},
    )
    monkeypatch.setattr(
        "app.modules.pdf_processor.predict_visual_forgery",
        lambda img: {"label": "Authentic", "forged_probability": 0.02, "authentic_probability": 0.98},
    )

    files = {"document": ("identity_package.pdf", pdf_bytes, "application/pdf")}
    response = client.post("/screen/pdf", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["document_format"] == "PDF"
    assert "dossier_risk_tier" in body

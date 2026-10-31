"""
ARGUS — PDF Dossier Ingestion & Forensic Processing Module

Provides end-to-end multi-page PDF ingestion, metadata forensics,
high-resolution page rasterization, digital text stream inspection,
and multi-page regulatory dossier risk aggregation.
"""

from __future__ import annotations

import os
import re
import tempfile
import warnings
from typing import Any, Dict, List, Optional, Tuple, Union

# PyTorch + NumPy / MKL can load duplicate Intel OpenMP runtimes on Windows.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np
from PIL import Image

# Prefer pymupdf, fallback to fitz
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

from app.modules.document_type_identification import identify_document_type
from app.modules.document_validation import validate_document
from app.modules.evidence_quality import assess_evidence_quality
from app.modules.forgery_model import predict_forgery as predict_visual_forgery
from app.modules.forgery_prediction import predict_forgery as predict_rule_forgery
from app.modules.ocr_extraction import extract_document_fields
from app.modules.risk_engine import compute_risk_score
from app.modules.tampering_detection import analyze_tampering


# Known desktop graphics/editing software that indicates synthetic tampering
# when found in official government / regulatory accreditation PDF metadata.
SUSPICIOUS_PRODUCERS_AND_CREATORS = [
    "photoshop",
    "gimp",
    "canva",
    "coreldraw",
    "illustrator",
    "inkscape",
    "sejda",
    "ilovepdf",
    "pdfescape",
    "paint.net",
    "pixlr",
    "affinity photo",
    "pdf editor",
]


def is_pdf(file_path_or_bytes: Union[str, bytes]) -> bool:
    """
    Check if the input is a valid PDF file by path or magic bytes (%PDF-).
    """
    if isinstance(file_path_or_bytes, bytes):
        return file_path_or_bytes[:5] == b"%PDF-"

    if isinstance(file_path_or_bytes, str):
        if not os.path.exists(file_path_or_bytes):
            return file_path_or_bytes.lower().endswith(".pdf")
        try:
            with open(file_path_or_bytes, "rb") as f:
                header = f.read(5)
            return header == b"%PDF-"
        except OSError:
            return file_path_or_bytes.lower().endswith(".pdf")

    return False


def inspect_pdf_metadata(doc: fitz.Document) -> Dict[str, Any]:
    """
    Extract and inspect PDF document metadata for forensic tampering signals.
    """
    raw_meta = doc.metadata or {}
    creator = str(raw_meta.get("creator") or "").strip()
    producer = str(raw_meta.get("producer") or "").strip()
    title = str(raw_meta.get("title") or "").strip()
    author = str(raw_meta.get("author") or "").strip()
    creation_date = str(raw_meta.get("creationDate") or "").strip()
    mod_date = str(raw_meta.get("modDate") or "").strip()

    combined_software = f"{creator} {producer}".lower()

    flags: List[str] = []
    suspicious_software_detected = False

    for sw in SUSPICIOUS_PRODUCERS_AND_CREATORS:
        if sw in combined_software:
            software_label = creator if creator else producer
            flags.append(
                f"PDF metadata identifies editing software: '{sw.title()}' ({software_label})"
            )
            suspicious_software_detected = True
            break

    # Flag modification after creation if dates differ substantially
    if creation_date and mod_date and creation_date != mod_date:
        flags.append(
            f"PDF was modified after initial creation (Created: {creation_date}, Modified: {mod_date})"
        )

    metadata_risk_score = 0.85 if suspicious_software_detected else (0.15 if flags else 0.0)

    return {
        "title": title,
        "author": author,
        "creator": creator,
        "producer": producer,
        "creation_date": creation_date,
        "modification_date": mod_date,
        "page_count": doc.page_count,
        "suspicious_software": suspicious_software_detected,
        "flags": flags,
        "metadata_risk_score": metadata_risk_score,
    }


def rasterize_pdf_page(
    doc: fitz.Document,
    page_num: int,
    dpi: int = 200,
) -> Tuple[np.ndarray, Image.Image]:
    """
    Rasterize a specific zero-indexed PDF page into an RGB numpy array and PIL Image.
    """
    if fitz is None:
        raise ImportError("PyMuPDF is required for PDF rasterization.")

    page = doc[page_num]
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)

    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
    pil_image = Image.fromarray(img_array)

    return img_array, pil_image


def extract_pdf_page_digital_text(page: fitz.Page) -> Dict[str, Any]:
    """
    Extract native digital text stream and font information from a PDF page.
    """
    text = page.get_text("text").strip()
    char_count = len(text)
    has_digital_text = char_count > 0

    font_names = set()
    try:
        font_info = page.get_fonts()
        for font in font_info:
            if len(font) >= 4 and font[3]:
                font_names.add(font[3])
    except Exception:
        pass

    return {
        "text": text,
        "has_digital_text": has_digital_text,
        "char_count": char_count,
        "fonts": sorted(list(font_names)),
    }


def screen_pdf_dossier(
    pdf_path_or_bytes: Union[str, bytes],
    live_photo_path: Optional[str] = None,
    max_pages: Optional[int] = 10,
    dpi: int = 200,
) -> Dict[str, Any]:
    """
    Execute the complete ARGUS multi-page regulatory screening pipeline on a PDF dossier.
    """
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) is required to process PDF dossiers.")

    temp_files: List[str] = []

    try:
        if isinstance(pdf_path_or_bytes, bytes):
            doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
        else:
            doc = fitz.open(pdf_path_or_bytes)

        total_pages = doc.page_count
        if max_pages is not None and max_pages > 0:
            pages_to_process = min(total_pages, max_pages)
        else:
            pages_to_process = total_pages

        partial_coverage = pages_to_process < total_pages

        # 1. Inspect Document-Level Metadata
        meta_audit = inspect_pdf_metadata(doc)

        pages_results: List[Dict[str, Any]] = []
        dossier_deficiencies: List[str] = []

        if partial_coverage:
            dossier_deficiencies.append(
                f"Partial dossier coverage: Only {pages_to_process} of {total_pages} pages were screened "
                f"(cap: {max_pages} pages). The remaining {total_pages - pages_to_process} pages were not evaluated."
            )

        if meta_audit.get("flags"):
            for flag in meta_audit["flags"]:
                dossier_deficiencies.append(f"Dossier Metadata: {flag}")

        max_risk_score = 0.0
        risk_tier_priority = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INCONCLUSIVE": 0}
        highest_tier = "LOW"

        # 2. Process Page-by-Page
        for p_idx in range(pages_to_process):
            page = doc[p_idx]
            page_num = p_idx + 1

            digital_stream = extract_pdf_page_digital_text(page)
            _, pil_img = rasterize_pdf_page(doc, p_idx, dpi=dpi)

            temp_fd, temp_img_path = tempfile.mkstemp(suffix=f"_argus_p{page_num}.png")
            os.close(temp_fd)
            temp_files.append(temp_img_path)
            pil_img.save(temp_img_path, format="PNG")

            # 1. OCR Extraction
            ocr_fields = extract_document_fields(temp_img_path)

            # 2. Document Type Identification (from OCR)
            doc_type_info = identify_document_type(ocr_fields)
            doc_type = doc_type_info.get("document_type", "unknown")

            # 3. Document Validation
            validation_info = validate_document(ocr_fields)

            # 4. Rule-Based Forgery
            rule_forgery_info = predict_rule_forgery(ocr_fields, validation_info)

            # 5. Visual Deep-Learning Forgery (EfficientNet-B0)
            try:
                visual_model_info = predict_visual_forgery(pil_img)
            except Exception as e:
                visual_model_info = {
                    "label": "UNAVAILABLE",
                    "class_id": None,
                    "authentic_probability": None,
                    "forged_probability": None,
                    "error": str(e),
                }

            # 6. ELA & Tampering Analysis
            tamper_info = analyze_tampering(temp_img_path)
            tamper_score = float(tamper_info.get("tampering_score", 0.0))
            ela_score = float(tamper_info.get("ela_score", 0.0))

            # 7. Evidence Quality
            try:
                evidence_quality = assess_evidence_quality(
                    ocr_result=ocr_fields,
                    document_type=doc_type_info,
                    validation=validation_info,
                    forgery=rule_forgery_info,
                    visual_model=visual_model_info,
                )
            except Exception:
                evidence_quality = None

            # 8. Face verification (optional live photo on page 1)
            face_result: Dict[str, Any]
            if live_photo_path and p_idx == 0:
                from app.modules.face_verification import verify_face
                face_result = verify_face(temp_img_path, live_photo_path)
            else:
                face_result = {
                    "performed": False,
                    "match": None,
                    "similarity": None,
                    "note": "No live photo provided",
                }

            # 9. Compute Page Risk Score
            combined_forgery = {
                "rules": rule_forgery_info,
                "visual_model": visual_model_info,
            }

            page_risk = compute_risk_score(
                validation=validation_info,
                forgery=combined_forgery,
                tampering=tamper_info,
                face=face_result,
                evidence_quality=evidence_quality,
            )

            p_score = float(page_risk.get("score") if "score" in page_risk else page_risk.get("risk_score", 0.0))
            p_tier = page_risk.get("tier") or page_risk.get("risk_tier", "LOW")

            # Track deficiencies
            page_deficiencies: List[str] = []
            for reason in page_risk.get("reasons", []):
                msg = f"Page {page_num} ({doc_type}): {reason}"
                page_deficiencies.append(msg)
                dossier_deficiencies.append(msg)

            # Digital text vs OCR consistency check
            if digital_stream["has_digital_text"]:
                ocr_raw_text = " ".join(
                    str(v) for v in ocr_fields.get("fields", {}).values() if v
                ).lower()
                if not ocr_raw_text and len(digital_stream["text"]) > 100:
                    discrepancy_msg = (
                        f"Page {page_num}: Digital text stream exists ({digital_stream['char_count']} chars) "
                        "but visual OCR extraction failed (possible hidden text or rendering anomaly)."
                    )
                    page_deficiencies.append(discrepancy_msg)
                    dossier_deficiencies.append(discrepancy_msg)

            if risk_tier_priority.get(p_tier, 0) > risk_tier_priority.get(highest_tier, 0):
                highest_tier = p_tier

            max_risk_score = max(max_risk_score, p_score)

            visual_forged_p = visual_model_info.get("forged_probability")
            pages_results.append({
                "page_number": page_num,
                "document_type": doc_type,
                "document_type_confidence": doc_type_info.get("confidence", 0.0),
                "risk_tier": p_tier,
                "risk_score": p_score,
                "tampering_score": tamper_score,
                "ela_score": ela_score,
                "visual_model": visual_model_info,
                "has_digital_text": digital_stream["has_digital_text"],
                "char_count": digital_stream["char_count"],
                "deficiencies": page_deficiencies,
            })

        doc.close()

        # If metadata indicates desktop Photoshop tampering on regulatory doc, ensure at least HIGH
        if meta_audit.get("suspicious_software") and highest_tier in ("LOW", "MEDIUM"):
            highest_tier = "HIGH"
            max_risk_score = max(max_risk_score, 75.0)

        unique_deficiencies = list(dict.fromkeys(dossier_deficiencies))
        if highest_tier in ("MEDIUM", "HIGH", "CRITICAL"):
            decision = "MANUAL_REVIEW"
        elif partial_coverage:
            decision = "MANUAL_REVIEW"
        else:
            decision = "LIKELY_AUTHENTIC"

        return {
            "document_format": "PDF",
            "total_pages": total_pages,
            "pages_processed": pages_to_process,
            "partial_coverage": partial_coverage,
            "dossier_risk_tier": highest_tier,
            "dossier_risk_score": round(max_risk_score, 1),
            "risk": {
                "score": round(max_risk_score, 1),
                "tier": highest_tier,
                "decision": decision,
                "reasons": unique_deficiencies,
            },
            "metadata_audit": meta_audit,
            "findings_summary": unique_deficiencies,
            "pages": pages_results,
            "decision": decision,
        }

    finally:
        for fpath in temp_files:
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass

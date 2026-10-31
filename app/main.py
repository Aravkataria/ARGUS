"""
ARGUS — Authentication & Recognition Guardian for Unified Screening

FastAPI entry point.

Pipeline
--------
Uploaded document
        │
        ├── OCR / MRZ extraction
        │
        ├── Document type identification
        │
        ├── Rule / database validation
        │
        ├── Rule-based forgery analysis
        │
        ├── Visual forgery model (EfficientNet)
        │
        ├── Evidence-quality assessment
        │
        ├── ELA / metadata tampering analysis
        │
        └── Optional face verification
                    │
                    ▼
              Risk Engine
                    │
                    ▼
             Final ARGUS result
"""

# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================

import os

# PyTorch + NumPy / MKL can load duplicate Intel OpenMP runtimes on Windows.
# This prevents the hard OMP #15 crash during inference.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


# ============================================================================
# SSL / CERTIFICATE SETUP
# ============================================================================

import functools
import ssl

try:
    import certifi

    ssl._create_default_https_context = functools.partial(
        ssl.create_default_context,
        cafile=certifi.where(),
    )
except ImportError:
    pass


# ============================================================================
# STANDARD LIBRARY
# ============================================================================

import shutil
import uuid
from typing import Any, Dict, Optional


# ============================================================================
# FASTAPI
# ============================================================================

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware


# ============================================================================
# ARGUS MODULES
# ============================================================================

from app.modules.ocr_extraction import extract_document_fields
from app.modules.document_validation import validate_document
from app.modules.document_type_identification import identify_document_type
from app.modules.tampering_detection import analyze_tampering
from app.modules.face_verification import verify_face
from app.modules.forgery_prediction import predict_forgery
from app.modules.forgery_model import predict_forgery as predict_visual_forgery
from app.modules.risk_engine import compute_risk_score
from app.modules.evidence_quality import assess_evidence_quality
from app.modules.pdf_processor import is_pdf, screen_pdf_dossier


# ============================================================================
# APP
# ============================================================================

app = FastAPI(
    title="ARGUS",
    description="AI-Based Fake Identity & Document Screening System",
    version="1.0.0",
)


# ============================================================================
# CORS
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# STORAGE
# ============================================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "app",
    "data",
    "uploads",
)

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ============================================================================
# HELPERS
# ============================================================================

def _save_upload(file: UploadFile) -> str:
    """
    Save an uploaded file to ARGUS's temporary upload directory.

    Returns
    -------
    str
        Absolute path to the saved file.
    """

    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file has no filename",
        )

    ext = os.path.splitext(file.filename)[1].lower()

    if not ext:
        ext = ".jpg"

    filename = f"{uuid.uuid4().hex}{ext}"

    path = os.path.join(
        UPLOAD_DIR,
        filename,
    )

    with open(path, "wb") as buffer:
        shutil.copyfileobj(
            file.file,
            buffer,
        )

    return path


def _safe_remove(path: Optional[str]) -> None:
    """
    Safely delete a temporary upload.
    """

    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ============================================================================
# HEALTH
# ============================================================================

@app.get("/health")
def health():
    """
    Basic API health check.
    """

    return {
        "status": "ok",
        "system": "ARGUS",
    }


# ============================================================================
# SCREEN
# ============================================================================

@app.post("/screen")
async def screen_document(
    document: UploadFile = File(...),
    live_photo: Optional[UploadFile] = File(None),
    max_pages: Optional[int] = Form(None),
):
    """
    Run the complete ARGUS screening pipeline.

    Parameters
    ----------
    document:
        Identity/document image.

    live_photo:
        Optional live/selfie image used for face verification.

    Returns
    -------
    dict
        Complete ARGUS evidence and risk assessment.
    """

    # ------------------------------------------------------------------------
    # INPUT VALIDATION
    # ------------------------------------------------------------------------

    document_content_type = (
        document.content_type or ""
    ).lower()

    doc_filename = (document.filename or "").lower()
    is_pdf_upload = (
        document_content_type in ("application/pdf", "application/x-pdf")
        or doc_filename.endswith(".pdf")
    )

    if not is_pdf_upload and not document_content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Document must be an image or PDF file",
        )

    if live_photo:

        live_content_type = (
            live_photo.content_type or ""
        ).lower()

        if not live_content_type.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail="Live photo must be an image file",
            )

    # ------------------------------------------------------------------------
    # SAVE UPLOADS
    # ------------------------------------------------------------------------

    doc_path = _save_upload(document)

    live_path = (
        _save_upload(live_photo)
        if live_photo
        else None
    )

    try:

        if is_pdf_upload or is_pdf(doc_path):
            pdf_kwargs: Dict[str, Any] = {
                "pdf_path_or_bytes": doc_path,
                "live_photo_path": live_path,
            }
            if max_pages is not None and max_pages > 0:
                pdf_kwargs["max_pages"] = max_pages
            return screen_pdf_dossier(**pdf_kwargs)

        # ====================================================================
        # MODULE 1 — OCR + MRZ EXTRACTION
        # ====================================================================

        ocr_result = extract_document_fields(
            doc_path
        )


        # ====================================================================
        # DOCUMENT TYPE IDENTIFICATION
        # ====================================================================

        document_type_result = identify_document_type(
            ocr_result
        )


        # ====================================================================
        # MODULE 2 — RULE / DATABASE VALIDATION
        # ====================================================================

        validation_result = validate_document(
            ocr_result
        )


        # ====================================================================
        # RULE-BASED FORGERY ANALYSIS
        # ====================================================================

        rule_forgery_result = predict_forgery(
            ocr_result,
            validation_result,
        )


        # ====================================================================
        # VISUAL FORGERY MODEL
        # ====================================================================

        # EfficientNet / trained ARGUS visual model.
        #
        # This model receives the actual document image rather than OCR
        # output. Therefore it provides an independent pixel-level signal.
        #
        # Example output:
        #
        # {
        #     "label": "Authentic",
        #     "class_id": 0,
        #     "authentic_probability": 0.77,
        #     "forged_probability": 0.23
        # }

        try:

            from PIL import Image

            with Image.open(doc_path) as image:

                visual_model_result = predict_visual_forgery(
                    image
                )

        except Exception as exc:

            # Do NOT make the entire screening pipeline fail because the
            # optional visual model failed.

            visual_model_result = {
                "label": "UNAVAILABLE",
                "class_id": None,
                "authentic_probability": None,
                "forged_probability": None,
                "error": str(exc),
            }


        # ====================================================================
        # COMBINE RULE + VISUAL FORGERY RESULTS
        # ====================================================================

        forgery_result = {
            "rules": rule_forgery_result,
            "visual_model": visual_model_result,
        }


        # ====================================================================
        # EVIDENCE QUALITY
        # ====================================================================

        # This is extremely important.
        #
        # Example:
        #
        # An Aadhaar image may have:
        #   - no MRZ
        #   - weak OCR
        #   - badly extracted fields
        #
        # That does NOT mean the document is authentic.
        #
        # Evidence quality tells the risk engine how much confidence it
        # should place in the available evidence.

        try:

            evidence_quality = assess_evidence_quality(
                ocr_result=ocr_result,
                document_type=document_type_result,
                validation=validation_result,
                forgery=rule_forgery_result,
                visual_model=visual_model_result,
            )

        except Exception as exc:

            # Safe fallback.
            #
            # If evidence-quality analysis itself fails, we deliberately
            # mark the evidence as uncertain instead of pretending it is
            # high-quality.

            evidence_quality = {
                "score": 0.0,
                "tier": "UNKNOWN",
                "confidence": 0.0,
                "reasons": [
                    f"Evidence-quality analysis failed: {exc}"
                ],
            }


        # ====================================================================
        # MODULE 3 — TAMPERING DETECTION
        # ====================================================================

        try:

            tampering_result = analyze_tampering(
                doc_path
            )

        except Exception as exc:

            tampering_result = {
                "tampering_score": 0.0,
                "ela_score": 0.0,
                "flagged_regions": [],
                "block_analysis": {},
                "metadata": {
                    "software_tag": None,
                    "has_camera_metadata": False,
                    "has_datetime_metadata": False,
                    "flags": [
                        f"Tampering analysis unavailable: {exc}"
                    ],
                },
            }


        # ====================================================================
        # MODULE 4 — FACE VERIFICATION
        # ====================================================================

        if live_path:

            try:

                face_result = verify_face(
                    doc_path,
                    live_path,
                )

            except Exception as exc:

                face_result = {
                    "performed": False,
                    "match": None,
                    "similarity": None,
                    "note": f"Face verification failed: {exc}",
                }

        else:

            face_result = {
                "performed": False,
                "match": None,
                "similarity": None,
                "note": "No live photo provided",
            }


        # ====================================================================
        # FINAL RISK ENGINE
        # ====================================================================

        risk = compute_risk_score(
            validation=validation_result,
            forgery=forgery_result,
            tampering=tampering_result,
            face=face_result,
            evidence_quality=evidence_quality,
        )


        # ====================================================================
        # FINAL RESPONSE
        # ====================================================================

        return {

            # ---------------------------------------------------------------
            # OCR
            # ---------------------------------------------------------------

            "ocr": ocr_result,


            # ---------------------------------------------------------------
            # DOCUMENT TYPE
            # ---------------------------------------------------------------

            "document_type": document_type_result,


            # ---------------------------------------------------------------
            # VALIDATION
            # ---------------------------------------------------------------

            "validation": validation_result,


            # ---------------------------------------------------------------
            # FORGERY ANALYSIS
            # ---------------------------------------------------------------

            "forgery_prediction": forgery_result,


            # ---------------------------------------------------------------
            # EVIDENCE QUALITY
            # ---------------------------------------------------------------

            "evidence_quality": evidence_quality,


            # ---------------------------------------------------------------
            # TAMPERING
            # ---------------------------------------------------------------

            "tampering": tampering_result,


            # ---------------------------------------------------------------
            # FACE
            # ---------------------------------------------------------------

            "face_verification": face_result,


            # ---------------------------------------------------------------
            # FINAL RISK
            # ---------------------------------------------------------------

            "risk": risk,
        }

    finally:

        # ====================================================================
        # CLEANUP
        # ====================================================================

        _safe_remove(doc_path)
        _safe_remove(live_path)
# ARGUS Server initialized for SIH 2026 Smart Automation track.

# ARGUS Server: Optimized for SIH 2026 Smart Automation track.


# ============================================================================
# SCREEN PDF
# ============================================================================

@app.post("/screen/pdf")
async def screen_pdf_endpoint(
    document: UploadFile = File(...),
    live_photo: Optional[UploadFile] = File(None),
    max_pages: Optional[int] = Form(None),
):
    """
    Dedicated endpoint for multi-page regulatory PDF dossier screening.
    """
    return await screen_document(
        document=document,
        live_photo=live_photo,
        max_pages=max_pages,
    )

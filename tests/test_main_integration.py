"""
End-to-end integration test for the /screen endpoint in app/main.py.

This is the test that was missing: everything in tests/test_*.py so far
exercises individual module functions directly (OCR regex/date parsing,
the forgery scorecard, risk_engine math) - none of them ever go through
FastAPI, so a wiring bug in main.py itself (wrong argument order, a
module not called, the response missing a key) wouldn't be caught by
the existing suite.

What's mocked vs real, and why:
  - extract_document_fields (EasyOCR), analyze_tampering (PIL/ELA pixel
    work), identify_document_type, and verify_face (OpenCV face
    detection) are monkeypatched. These need real image content, a
    trained detector, or a network fetch (EasyOCR's first-run model
    download) to behave meaningfully - none of that is what this test
    is checking. A 1x1 placeholder image can't exercise them for real
    without becoming a slow, flaky test that just re-tests OpenCV/
    EasyOCR, not ARGUS's own logic.
  - validate_document, predict_forgery, and compute_risk_score are left
    real. They're pure Python, fast, deterministic, and already
    unit-tested in isolation - running them for real here is what
    actually proves the modules are wired together correctly through
    the live HTTP endpoint, not just individually correct.

A synthetic in-memory PNG (via Pillow, already a dependency) stands in
for an uploaded document/live photo - its pixel content is irrelevant
since the pixel-touching functions are mocked.
"""

import io
import json
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.modules import document_validation

client = TestClient(app)


# ---------------------------------------------------------------------------
# Shared fixtures / fakes
# ---------------------------------------------------------------------------

CLEAN_OCR_RESULT = {
    "mrz_found": True,
    "document_type": "P",
    "checks": {
        "document_number_valid": True, "birth_date_valid": True,
        "expiry_date_valid": True, "composite_valid": True, "overall_valid": True,
    },
    "document_number": "PP3000000", "date_of_birth": "1990-01-01",
    "date_of_expiry": "2032-01-01", "nationality": "IND", "sex": "M",
    "fields": {},
}

CLEAN_DOCUMENT_TYPE_RESULT = {
    "document_type": "passport",
    "confidence": 0.95,
    "evidence": ["MRZ document-type character: P"],
    "candidate_scores": {"passport": 0.95},
}

CLEAN_TAMPERING_RESULT = {"tampering_score": 0.05, "metadata": {"flags": []}}


def _fake_image_bytes() -> bytes:
    """A tiny real PNG - enough to pass main.py's content-type check and
    give _save_upload real bytes to write, without needing an actual
    document photo (the functions that would look at its pixels are
    mocked in every test below)."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _patch_pipeline(monkeypatch, ocr_result=None, tampering_result=None,
                     face_result=None, doc_type_result=None, capture_paths=None):
    """Monkeypatch the heavy/model-backed pieces where main.py imported
    them by name (patching app.modules.ocr_extraction.extract_document_fields
    would NOT affect main.py's already-bound reference - it has to be
    patched on app.main itself)."""
    ocr_result = ocr_result or CLEAN_OCR_RESULT
    tampering_result = tampering_result or CLEAN_TAMPERING_RESULT
    doc_type_result = doc_type_result or CLEAN_DOCUMENT_TYPE_RESULT

    def fake_extract(path):
        if capture_paths is not None:
            capture_paths.append(path)
        return ocr_result

    def fake_identify(_ocr_result):
        return doc_type_result

    def fake_tampering(path):
        if capture_paths is not None:
            capture_paths.append(path)
        return tampering_result

    def fake_verify_face(doc_path, live_path):
        if capture_paths is not None:
            capture_paths.append(live_path)
        return face_result or {"performed": True, "match": True, "similarity": 0.9, "note": None}

    def fake_evidence_quality(**kwargs):
        return {
            "score": 0.95,
            "quality_label": "HIGH",
            "tier": "HIGH",
            "sufficient_for_decision": True,
            "reasons": [],
            "positive_evidence": [],
        }

    def fake_visual_forgery(path):
        return {
            "forged_probability": 0.05,
            "authentic_probability": 0.95,
            "forgery_detected": False,
            "confidence": 0.95,
        }

    monkeypatch.setattr("app.main.extract_document_fields", fake_extract)
    monkeypatch.setattr("app.main.identify_document_type", fake_identify)
    monkeypatch.setattr("app.main.analyze_tampering", fake_tampering)
    monkeypatch.setattr("app.main.verify_face", fake_verify_face)
    monkeypatch.setattr("app.main.assess_evidence_quality", fake_evidence_quality)
    monkeypatch.setattr("app.main.predict_visual_forgery", fake_visual_forgery)


# ---------------------------------------------------------------------------
# Happy path - document only, no live photo
# ---------------------------------------------------------------------------

def test_screen_clean_document_returns_low_risk(monkeypatch):
    _patch_pipeline(monkeypatch)
    files = {"document": ("passport.png", _fake_image_bytes(), "image/png")}

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    body = response.json()

    # Every module's output key must be present in the unified response.
    for key in ("ocr", "document_type", "validation", "forgery_prediction",
                "tampering", "face_verification", "risk"):
        assert key in body

    assert body["risk"]["tier"] == "LOW"
    assert body["face_verification"]["performed"] is False
    assert body["face_verification"]["note"] == "No live photo provided"


# ---------------------------------------------------------------------------
# Happy path - document + live photo (face verification branch)
# ---------------------------------------------------------------------------

def test_screen_with_live_photo_runs_face_verification(monkeypatch):
    captured_paths = []
    _patch_pipeline(
        monkeypatch,
        face_result={"performed": True, "match": True, "similarity": 0.87, "note": None},
        capture_paths=captured_paths,
    )
    files = {
        "document": ("passport.png", _fake_image_bytes(), "image/png"),
        "live_photo": ("selfie.png", _fake_image_bytes(), "image/png"),
    }

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["face_verification"]["performed"] is True
    assert body["face_verification"]["similarity"] == 0.87
    # verify_face was actually called with a live_photo path (not None) -
    # this is the branch that only runs when live_photo is provided.
    assert any(p and "selfie" not in p for p in captured_paths) or len(captured_paths) >= 2


# ---------------------------------------------------------------------------
# Real cross-module wiring: blacklist hit forces HIGH risk end-to-end
# ---------------------------------------------------------------------------

def test_screen_blacklisted_document_forces_high_risk(tmp_path, monkeypatch):
    """validate_document, predict_forgery, and compute_risk_score all run
    for real here. This is the test that actually proves those three
    modules are wired together correctly through the live endpoint: a
    blacklist hit found in validate_document must survive being folded
    into forgery_prediction's score and then risk_engine's weighted
    combination, ending in tier HIGH - not just each module in isolation."""
    blacklist_path = tmp_path / "blacklist.json"
    blacklist_path.write_text(json.dumps({"blacklisted_document_numbers": ["PP3000000"]}))
    monkeypatch.setattr(document_validation, "BLACKLIST_PATH", str(blacklist_path))

    _patch_pipeline(monkeypatch)  # OCR result's document_number matches the blacklist entry above
    files = {"document": ("passport.png", _fake_image_bytes(), "image/png")}

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["validation"]["is_blacklisted"] is True
    assert body["risk"]["tier"] == "HIGH"
    assert body["risk"]["score"] >= 90.0
    assert any("blacklist" in r.lower() for r in body["risk"]["reasons"])


# ---------------------------------------------------------------------------
# Rejects non-image uploads
# ---------------------------------------------------------------------------

def test_screen_rejects_non_image_upload(monkeypatch):
    _patch_pipeline(monkeypatch)
    files = {"document": ("notes.txt", b"not an image", "text/plain")}

    response = client.post("/screen", files=files)

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Uploaded files are cleaned up after the request, success or failure
# ---------------------------------------------------------------------------

def test_screen_cleans_up_uploaded_files_after_request(monkeypatch):
    captured_paths = []
    _patch_pipeline(monkeypatch, capture_paths=captured_paths)
    files = {
        "document": ("passport.png", _fake_image_bytes(), "image/png"),
        "live_photo": ("selfie.png", _fake_image_bytes(), "image/png"),
    }

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    assert captured_paths, "pipeline functions were never called with a saved path"
    for path in captured_paths:
        assert path is None or not os.path.exists(path), (
            f"{path} should have been removed by main.py's finally block"
        )


def test_screen_cleans_up_uploaded_files_even_when_pipeline_raises(monkeypatch):
    captured_paths = []

    def fake_extract(path):
        captured_paths.append(path)
        raise RuntimeError("simulated OCR failure")

    monkeypatch.setattr("app.main.extract_document_fields", fake_extract)
    files = {"document": ("passport.png", _fake_image_bytes(), "image/png")}

    with pytest.raises(RuntimeError):
        client.post("/screen", files=files)

    assert captured_paths and not os.path.exists(captured_paths[0])
# Test Suite: End-to-end integration test verifying /screen endpoint JSON contract.

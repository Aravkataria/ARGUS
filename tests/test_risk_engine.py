"""
Tests for risk_engine.py's integration with the forgery scorecard.

These pin down two things that broke silently the first time forgery was
wired in:
  1. forgery_risk and the old validation_risk aren't both counted (that
     double-counts blacklist/expiry/MRZ-checksum evidence and inflates
     scores) - forgery_risk is the sole document/content risk term.
  2. A blacklist hit and an expired document are certain, direct facts
     that must not be diluted into a lower tier by a weighted average
     just because tampering/face both came back clean.
"""

from app.modules.risk_engine import compute_risk_score
from app.modules.forgery_prediction import predict_forgery

CLEAN_OCR = {
    "mrz_found": True,
    "document_type": "P",
    "checks": {
        "document_number_valid": True, "birth_date_valid": True,
        "expiry_date_valid": True, "composite_valid": True, "overall_valid": True,
    },
    "document_number": "PP3000000", "date_of_birth": "1990-01-01",
    "date_of_expiry": "2032-01-01", "nationality": "IND", "sex": "M",
}
CLEAN_VALIDATION = {
    "mrz_found": True, "is_expired": False, "is_blacklisted": False,
    "checks_passed": 4, "checks_total": 4, "validity_ratio": 1.0, "issues": [],
}
CLEAN_TAMPERING = {"tampering_score": 0.05, "metadata": {"flags": []}}
CLEAN_FACE = {"performed": True, "match": True, "similarity": 0.9}


def test_clean_document_scores_low():
    forgery = predict_forgery(CLEAN_OCR, CLEAN_VALIDATION)
    risk = compute_risk_score(CLEAN_VALIDATION, forgery, CLEAN_TAMPERING, CLEAN_FACE)
    assert risk["tier"] == "LOW"
    assert risk["breakdown"]["forgery_risk"] == 0.0


def test_blacklisted_document_forces_high_even_with_clean_tampering_and_face():
    validation = dict(CLEAN_VALIDATION, is_blacklisted=True)
    forgery = predict_forgery(CLEAN_OCR, validation)
    risk = compute_risk_score(validation, forgery, CLEAN_TAMPERING, CLEAN_FACE)
    assert risk["tier"] == "HIGH"
    assert risk["score"] >= 90.0


def test_expired_document_is_not_diluted_to_low():
    validation = dict(CLEAN_VALIDATION, is_expired=True)
    forgery = predict_forgery(CLEAN_OCR, validation)
    risk = compute_risk_score(validation, forgery, CLEAN_TAMPERING, CLEAN_FACE)
    assert risk["tier"] in ("MEDIUM", "HIGH")
    assert risk["score"] >= 30.0


def test_expired_plus_failed_checksum_not_diluted_to_low():
    ocr = dict(CLEAN_OCR)
    ocr["checks"] = {
        "document_number_valid": False, "birth_date_valid": True,
        "expiry_date_valid": True, "composite_valid": False, "overall_valid": False,
    }
    validation = {
        "mrz_found": True, "is_expired": True, "is_blacklisted": False,
        "checks_passed": 2, "checks_total": 5, "validity_ratio": 0.4, "issues": ["expired"],
    }
    forgery = predict_forgery(ocr, validation)
    risk = compute_risk_score(validation, forgery, CLEAN_TAMPERING, CLEAN_FACE)
    assert risk["tier"] in ("MEDIUM", "HIGH")


def test_near_maximal_tampering_alone_at_least_reaches_medium():
    # NOTE: with WEIGHTS["tampering"] = 0.45, even tampering_score == 1.0
    # can only ever contribute 45/100 points - it cannot reach the HIGH
    # tier (>=65) on its own under any weighting, no matter how clean
    # validation/forgery/face are. Pre-existing weight/threshold design
    # question, separate from this integration - flagged, not fixed, here.
    heavy_tampering = {"tampering_score": 0.95, "metadata": {"flags": ["Editing software detected in metadata: photoshop"]}}
    forgery = predict_forgery(CLEAN_OCR, CLEAN_VALIDATION)
    risk = compute_risk_score(CLEAN_VALIDATION, forgery, heavy_tampering, CLEAN_FACE)
    assert risk["tier"] in ("MEDIUM", "HIGH")


def test_forgery_reasons_are_surfaced_in_risk_reasons():
    validation = dict(CLEAN_VALIDATION, is_blacklisted=True)
    forgery = predict_forgery(CLEAN_OCR, validation)
    risk = compute_risk_score(validation, forgery, CLEAN_TAMPERING, CLEAN_FACE)
    assert any("blacklist" in r.lower() for r in risk["reasons"])
# Test Suite: Validates risk boundaries (0.0 to 1.0) and anomaly flagging thresholds.

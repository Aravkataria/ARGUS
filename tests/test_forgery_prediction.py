"""
Tests for forgery_prediction.py's scorecard signals - deterministic, no
image or EasyOCR required (same style as test_ocr.py / test_risk_engine.py).

Coverage here is deliberately focused on the two trickiest, most recently
added pieces: the MRZ-vs-printed-page cross-check (_check_mrz_visible_
consistency) and its interaction with the existing checksum/date-logic/
blacklist signals. See forgery_prediction.py's own docstrings for why each
guard rail (skip on partial dates, skip doc# comparison when the MRZ side
already failed its own checksum, etc.) exists - these tests pin that
behavior down so it can't silently regress.
"""

from app.modules.document_validation import validate_document
from app.modules.forgery_prediction import predict_forgery

BASE_OCR = {
    "mrz_found": True,
    "document_type": "P",
    "surname": "SHARMA",
    "given_names": "ARAV KUMAR",
    "document_number": "P1234567",
    "nationality": "IND",
    "date_of_birth": "950310",
    "date_of_expiry": "320515",
    "sex": "M",
    "checks": {
        "document_number_valid": True, "birth_date_valid": True,
        "expiry_date_valid": True, "composite_valid": True, "overall_valid": True,
    },
}


def _run(ocr):
    validation = validate_document(ocr)
    return predict_forgery(ocr, validation)


# --------------------------------------------------------------------------
# Clean document - baseline, nothing should fire
# --------------------------------------------------------------------------

def test_clean_document_is_likely_authentic():
    pred = _run(dict(BASE_OCR, fields={}))
    assert pred["label"] == "LIKELY_AUTHENTIC"
    assert pred["forgery_risk_score"] == 0.0


# --------------------------------------------------------------------------
# MRZ-vs-printed-page cross-check
# --------------------------------------------------------------------------

def test_surname_mismatch_between_mrz_and_printed_page_is_flagged():
    ocr = dict(BASE_OCR, fields={"surname": "PATEL"})
    pred = _run(ocr)
    assert pred["triggered_signals"].get("mrz_visible_mismatch") is True
    assert any("Surname" in r for r in pred["reasons"])
    assert pred["label"] == "SUSPICIOUS"


def test_matching_surname_is_not_flagged():
    ocr = dict(BASE_OCR, fields={"surname": "SHARMA"})
    pred = _run(ocr)
    assert "mrz_visible_mismatch" not in pred["triggered_signals"]


def test_document_number_mismatch_is_flagged():
    ocr = dict(BASE_OCR, fields={"document_number": "P9999999"})
    pred = _run(ocr)
    assert pred["triggered_signals"].get("mrz_visible_mismatch") is True
    assert any("Document number" in r for r in pred["reasons"])


def test_document_number_cross_check_skipped_when_mrz_checksum_already_failed():
    # Avoid double-reporting the same underlying evidence under two names.
    bad_checks = dict(BASE_OCR["checks"], document_number_valid=False, overall_valid=False)
    ocr = dict(BASE_OCR, checks=bad_checks, fields={"document_number": "P9999999"})
    pred = _run(ocr)
    assert "mrz_visible_mismatch" not in pred["triggered_signals"]
    assert pred["triggered_signals"].get("mrz_checksum_failed") is True


def test_complete_matching_date_is_not_flagged():
    ocr = dict(BASE_OCR, fields={"date_of_birth": "10 MAR 1995"})
    pred = _run(ocr)
    assert "mrz_visible_mismatch" not in pred["triggered_signals"]


def test_complete_mismatching_date_is_flagged():
    ocr = dict(BASE_OCR, fields={"date_of_birth": "10 MAR 1996"})
    pred = _run(ocr)
    assert pred["triggered_signals"].get("mrz_visible_mismatch") is True
    assert any("Date of birth" in r for r in pred["reasons"])


def test_partial_date_capture_is_not_falsely_flagged():
    # A date that split across two OCR boxes and only captured the day
    # number ("10") must never be compared - it isn't a complete date.
    ocr = dict(BASE_OCR, fields={"date_of_birth": "10"})
    pred = _run(ocr)
    assert "mrz_visible_mismatch" not in pred["triggered_signals"]


def test_cross_check_does_not_run_without_mrz():
    ocr = {"mrz_found": False, "fields": {"surname": "ANYTHING"}}
    pred = _run(ocr)
    assert "mrz_visible_mismatch" not in pred["triggered_signals"]


# --------------------------------------------------------------------------
# Confidence scoring: same point weight regardless of confidence (a
# confidence-based scoring adjustment would reward blurring exactly the
# region someone wants to hide), but the reason text carries confidence
# context, and low-confidence "extracted" fields don't count toward
# completeness.
# --------------------------------------------------------------------------

def test_checksum_failure_reason_notes_low_mrz_confidence():
    bad_checks = dict(BASE_OCR["checks"], document_number_valid=False, overall_valid=False)
    ocr = dict(BASE_OCR, checks=bad_checks, fields={}, mrz_ocr_confidence=0.35)
    pred = _run(ocr)
    assert any("35%" in r and "plausible explanation" in r for r in pred["reasons"])


def test_checksum_failure_reason_notes_high_mrz_confidence():
    bad_checks = dict(BASE_OCR["checks"], document_number_valid=False, overall_valid=False)
    ocr = dict(BASE_OCR, checks=bad_checks, fields={}, mrz_ocr_confidence=0.9)
    pred = _run(ocr)
    assert any("90%" in r and "less likely to be simple OCR noise" in r for r in pred["reasons"])


def test_confidence_does_not_change_point_weight():
    # Same underlying failure, only mrz_ocr_confidence differs - score must
    # be identical either way (confidence informs the reason text only).
    bad_checks = dict(BASE_OCR["checks"], document_number_valid=False, overall_valid=False)
    low_conf = _run(dict(BASE_OCR, checks=bad_checks, fields={}, mrz_ocr_confidence=0.1))
    high_conf = _run(dict(BASE_OCR, checks=bad_checks, fields={}, mrz_ocr_confidence=0.99))
    assert low_conf["forgery_risk_score"] == high_conf["forgery_risk_score"]


def test_low_confidence_field_does_not_count_toward_completeness():
    ocr = {
        "mrz_found": False,
        "fields": {"document_number": "X1", "surname": "S", "given_names": "G",
                    "date_of_birth": "2000-01-01", "nationality": "TESTLAND"},
        "field_confidence": {"document_number": 0.05},  # barely-committed OCR read
        "document_number": "X1", "date_of_birth": "2000-01-01", "nationality": "TESTLAND",
    }
    pred = _run(ocr)
    # document_number would otherwise count as present for "national_id"
    # completeness - at confidence 0.05 it should not.
    assert pred["field_completeness"] < 1.0
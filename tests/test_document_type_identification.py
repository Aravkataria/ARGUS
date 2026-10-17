"""
Tests for document_type_identification.py - deterministic, built on small
constructed ocr_result dicts (same style as test_forgery_prediction.py),
no image or EasyOCR required.

Coverage exercises each of the four signals independently (so a future
change to one doesn't silently break another) and a couple of realistic
multi-signal combinations pulled from what was actually observed against
real specimen images during testing.
"""

from app.modules.document_type_identification import identify_document_type


def test_mrz_type_char_identifies_passport():
    ocr = {"mrz_found": True, "document_type": "P", "raw_text": [], "fields": {}}
    result = identify_document_type(ocr)
    assert result["document_type"] == "passport"
    assert result["confidence"] > 0


def test_mrz_type_char_identifies_visa():
    ocr = {"mrz_found": True, "document_type": "V", "raw_text": [], "fields": {}}
    result = identify_document_type(ocr)
    assert result["document_type"] == "visa"


def test_mrz_type_char_identifies_national_id_variants():
    for type_char in ["A", "C", "I"]:
        ocr = {"mrz_found": True, "document_type": type_char, "raw_text": [], "fields": {}}
        result = identify_document_type(ocr)
        assert result["document_type"] == "national_id"


def test_title_keyword_alone_identifies_driving_license():
    ocr = {"mrz_found": False, "raw_text": ["UTOPIA DRIVING LICENCE"], "fields": {}}
    result = identify_document_type(ocr)
    assert result["document_type"] == "driving_license"


def test_field_evidence_alone_identifies_visa():
    ocr = {"mrz_found": False, "raw_text": [], "fields": {"visa_number": "V123", "visa_type": "TOURIST"}}
    result = identify_document_type(ocr)
    assert result["document_type"] == "visa"


def test_no_signals_returns_unknown_with_zero_confidence():
    ocr = {"mrz_found": False, "raw_text": ["some unrelated noise"], "fields": {}}
    result = identify_document_type(ocr)
    assert result["document_type"] == "unknown"
    assert result["confidence"] == 0.0


def test_agreeing_signals_produce_high_confidence():
    # Mirrors the real SHARMA/Eolie passport specimens: MRZ type char,
    # MRZ format, and printed title all agree.
    ocr = {
        "mrz_found": True, "document_type": "P", "mrz_format": "TD3",
        "raw_text": ["REPUBLIC OF UTOPIA", "PASSPORT"], "fields": {},
    }
    result = identify_document_type(ocr)
    assert result["document_type"] == "passport"
    assert result["confidence"] == 1.0
    assert len(result["evidence"]) == 3


def test_conflicting_signals_are_both_scored_and_reported():
    # Contrived: MRZ says passport but title keyword says visa - the
    # candidate_scores breakdown should show both, not just the winner.
    ocr = {
        "mrz_found": True, "document_type": "P", "mrz_format": "TD3",
        "raw_text": ["VISA"], "fields": {},
    }
    result = identify_document_type(ocr)
    assert "passport" in result["candidate_scores"]
    assert "visa" in result["candidate_scores"]
    assert result["candidate_scores"]["passport"] > result["candidate_scores"]["visa"]
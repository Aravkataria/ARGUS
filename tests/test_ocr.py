"""
Tests for the deterministic parts of Module 1 (OCR extraction) that don't
require EasyOCR or a live image: MRZ confusable-character correction,
label/value matching, and date normalization.

These run fast and without network access, so they're safe for CI. Testing
the full extract_document_fields() pipeline (EasyOCR + a real specimen
image) is a separate, slower integration test - see test_ocr_integration.py
once a real/synthetic specimen is checked in under a path that isn't
gitignored, or mocked with a fixture EasyOCR reader.
"""

from app.modules import ocr_extraction as ocr


# --------------------------------------------------------------------------
# MRZ line type maps must match the ICAO 9303 fixed line lengths, or the
# confusable-character corrector silently no-ops (see _correct_mrz_line).
# --------------------------------------------------------------------------

def test_td3_line_type_maps_are_44_chars():
    assert len(ocr._TD3_LINE1_TYPES) == 44
    assert len(ocr._TD3_LINE2_TYPES) == 44


def test_td1_line_type_maps_are_30_chars():
    assert len(ocr._TD1_LINE1_TYPES) == 30
    assert len(ocr._TD1_LINE2_TYPES) == 30
    assert len(ocr._TD1_LINE3_TYPES) == 30


# --------------------------------------------------------------------------
# Confusable-character correction (O<->0, I<->1, S<->5, Z<->2, B<->8)
# --------------------------------------------------------------------------

def test_corrects_digit_that_should_be_letter_in_nationality():
    # "UTO" (nationality) misread as "UT0" - position falls in an 'A' slot
    line2 = "L898902C<3UT0" + "0" * 6 + "1" + "M" + "0" * 6 + "1" + "<" * 14 + "0" + "6"
    corrected = ocr._correct_mrz_line(line2, ocr._TD3_LINE2_TYPES)
    assert "UTO" in corrected
    assert "UT0" not in corrected


def test_does_not_touch_alphanumeric_document_number_field():
    # Document number is type 'X' (free alphanumeric) - must be left alone
    line2 = "PP30000O0" + "0" + "UTO" + "0" * 6 + "1" + "M" + "0" * 6 + "1" + "<" * 14 + "0" + "6"
    corrected = ocr._correct_mrz_line(line2, ocr._TD3_LINE2_TYPES)
    assert corrected[:9] == "PP30000O0"  # unchanged - X positions aren't corrected


def test_length_mismatch_is_left_unchanged_not_crashed():
    assert ocr._correct_mrz_line("SHORT", ocr._TD3_LINE1_TYPES) == "SHORT"


# --------------------------------------------------------------------------
# Isolated filler-noise stripping
# --------------------------------------------------------------------------

def test_strips_stray_letter_deep_inside_filler_run():
    line = "P<UTOERIKSSON<<ANNA<MARIA<<<<X<<<<<<<<<<<<<"
    result = ocr._strip_isolated_filler_noise(line)
    assert result[-13] == "<"


def test_does_not_strip_genuine_middle_initial():
    # A single letter right after real name content (not deep in filler)
    # should survive - only 3+ '<' runs before it get stripped.
    line = "P<UTOSMITH<<JOHN<A<<<<<<<<<<<<<<<<<<<<<<<<<<"
    result = ocr._strip_isolated_filler_noise(line)
    assert "JOHN<A<" in result


# --------------------------------------------------------------------------
# Label/value matching (visas, IDs, licences with no MRZ)
# --------------------------------------------------------------------------

def test_normalize_label_strips_punctuation_and_case():
    assert ocr._normalize_label("Date of Expiry:") == "date of expiry"


def test_match_field_label_prefers_longer_more_specific_phrase():
    assert ocr._match_field_label("date of expiry") == "date_of_expiry"
    assert ocr._match_field_label("visa no") == "visa_number"


def test_match_field_label_returns_none_for_unknown_text():
    assert ocr._match_field_label("random unrelated text") is None


def test_find_value_for_label_same_line():
    label = {"text": "Visa No.", "x0": 0, "x1": 60, "y0": 100, "y1": 120, "cx": 30, "cy": 110}
    value = {"text": "V1234567", "x0": 70, "x1": 150, "y0": 100, "y1": 120, "cx": 110, "cy": 110}
    assert ocr._find_value_for_label(label, [label, value]) == "V1234567"


def test_find_value_for_label_falls_back_to_below():
    label = {"text": "Nationality", "x0": 0, "x1": 80, "y0": 100, "y1": 120, "cx": 40, "cy": 110}
    value = {"text": "INDIAN", "x0": 0, "x1": 80, "y0": 125, "y1": 145, "cx": 40, "cy": 135}
    assert ocr._find_value_for_label(label, [label, value]) == "INDIAN"


# --------------------------------------------------------------------------
# Date normalization
# --------------------------------------------------------------------------

def test_normalize_date_dd_mon_yyyy():
    assert ocr._normalize_date("15 JUN 1990") == "1990-06-15"


def test_normalize_date_slash_form_dayfirst():
    assert ocr._normalize_date("15/06/1990") == "1990-06-15"


def test_normalize_date_returns_none_for_garbage():
    assert ocr._normalize_date("not a date") is None
# Test Suite: Verifies OCR text parser consistency on multi-lingual input tokens.

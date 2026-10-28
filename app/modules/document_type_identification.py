"""
ARGUS — Document Type Identification
=====================================

Identifies the likely document type from OCR-extracted information.

Supported document types
-------------------------
    - passport
    - visa
    - driving_license
    - national_id
    - unknown

Design goals
------------
1. Do NOT force an unknown document into a known type.
2. Return an explicit confidence score.
3. Return evidence explaining why a type was selected.
4. Return candidate scores for debugging/calibration.
5. Prefer strong structural evidence over generic keywords.
6. Keep this module independent from forgery prediction.
7. Provide one authoritative document-type result for the rest of ARGUS.

Important
---------
This module identifies the DOCUMENT TYPE only.

It does NOT decide whether the document is:
    - authentic
    - forged
    - suspicious

Those decisions belong to the other ARGUS modules.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# ============================================================================
# CONFIGURATION
# ============================================================================

SUPPORTED_DOCUMENT_TYPES = (
    "passport",
    "visa",
    "driving_license",
    "national_id",
    "unknown",
)


# Minimum score required before we are willing to identify a document.
MIN_IDENTIFICATION_SCORE = 35.0

# Minimum confidence required for a non-unknown result.
MIN_IDENTIFICATION_CONFIDENCE = 0.60

# Required margin between the best and second-best candidate.
#
# This prevents:
#
#     national_id = 62
#     driving_license = 60
#
# from being confidently classified as national_id.
MIN_SCORE_MARGIN = 10.0


# ============================================================================
# NORMALIZATION HELPERS
# ============================================================================

def _safe_text(value: Any) -> str:
    """Convert a value into normalized text."""

    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        return " ".join(
            _safe_text(item)
            for item in value
        )

    if isinstance(value, dict):
        return " ".join(
            f"{_safe_text(key)} {_safe_text(val)}"
            for key, val in value.items()
        )

    return str(value)


def _normalize_text(value: Any) -> str:
    """
    Normalize OCR text for keyword matching.
    """

    text = _safe_text(value)

    text = text.upper()

    text = re.sub(
        r"[^A-Z0-9\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _all_ocr_text(ocr_result: Dict[str, Any]) -> str:
    """
    Build one searchable text representation from OCR output.

    This intentionally includes:
        - top-level fields
        - extracted fields
        - raw OCR text
        - OCR blocks when available

    It does NOT include model predictions.
    """

    parts: List[str] = []

    # ------------------------------------------------------------------------
    # Top-level textual fields
    # ------------------------------------------------------------------------

    for key in (
        "document_number",
        "surname",
        "given_names",
        "nationality",
        "sex",
        "date_of_birth",
        "date_of_issue",
        "date_of_expiry",
        "visa_number",
        "visa_type",
        "license_class",
        "document_type",
    ):
        value = ocr_result.get(key)

        if value is not None:
            parts.append(
                _safe_text(value)
            )

    # ------------------------------------------------------------------------
    # Extracted fields
    # ------------------------------------------------------------------------

    fields = ocr_result.get(
        "fields",
        {},
    )

    if isinstance(fields, dict):

        for key, value in fields.items():

            parts.append(
                _safe_text(key)
            )

            parts.append(
                _safe_text(value)
            )

    # ------------------------------------------------------------------------
    # Raw OCR text
    # ------------------------------------------------------------------------

    for key in (
        "text",
        "raw_text",
        "ocr_text",
        "full_text",
    ):
        value = ocr_result.get(key)

        if value:
            parts.append(
                _safe_text(value)
            )

    # ------------------------------------------------------------------------
    # OCR blocks
    # ------------------------------------------------------------------------

    blocks = ocr_result.get(
        "blocks",
        [],
    )

    if isinstance(blocks, list):

        for block in blocks:

            if isinstance(block, dict):

                value = (
                    block.get("text")
                    or block.get("value")
                    or ""
                )

                if value:
                    parts.append(
                        _safe_text(value)
                    )

            elif block:
                parts.append(
                    _safe_text(block)
                )

    return _normalize_text(
        " ".join(parts)
    )


def _get_fields(
    ocr_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Safely retrieve extracted fields.
    """

    fields = ocr_result.get(
        "fields",
        {},
    )

    if isinstance(fields, dict):
        return fields

    return {}


def _has_field(
    ocr_result: Dict[str, Any],
    field_name: str,
) -> bool:
    """
    Check whether a field contains meaningful information.

    Checks both:
        ocr_result[field]
        ocr_result["fields"][field]
    """

    direct_value = ocr_result.get(
        field_name
    )

    if direct_value not in (
        None,
        "",
        [],
        {},
    ):
        return True

    fields = _get_fields(
        ocr_result
    )

    value = fields.get(
        field_name
    )

    return value not in (
        None,
        "",
        [],
        {},
    )


# ============================================================================
# KEYWORD HELPERS
# ============================================================================

def _contains_any(
    text: str,
    keywords: Tuple[str, ...],
) -> List[str]:
    """
    Return keywords found in normalized OCR text.
    """

    found = []

    for keyword in keywords:

        keyword_normalized = _normalize_text(
            keyword
        )

        if not keyword_normalized:
            continue

        # Word-boundary matching prevents:
        #
        #     VISA
        #
        # from accidentally matching an unrelated substring.
        pattern = (
            r"\b"
            + re.escape(keyword_normalized)
            + r"\b"
        )

        if re.search(
            pattern,
            text,
        ):
            found.append(
                keyword
            )

    return found


# ============================================================================
# DOCUMENT-SPECIFIC SIGNALS
# ============================================================================

PASSPORT_KEYWORDS = (
    "PASSPORT",
    "PASAPORTE",
    "PASSEPORT",
    "REISEPASS",
    "TRAVEL DOCUMENT",
)


VISA_KEYWORDS = (
    "VISA",
    "ENTRY VISA",
    "VISA TYPE",
    "VISA NUMBER",
    "VALID UNTIL",
    "ENTRIES",
)


DRIVING_LICENSE_KEYWORDS = (
    "DRIVING LICENCE",
    "DRIVING LICENSE",
    "DRIVER LICENSE",
    "DRIVER LICENCE",
    "DL NO",
    "LICENCE NO",
    "LICENSE NO",
    "LICENSE NUMBER",
    "LICENCE NUMBER",
    "CLASS",
    "VEHICLE CLASS",
)


NATIONAL_ID_KEYWORDS = (
    "NATIONAL ID",
    "NATIONAL IDENTITY",
    "IDENTITY CARD",
    "IDENTIFICATION CARD",
    "IDENTITY DOCUMENT",
)


# ============================================================================
# MRZ DETECTION
# ============================================================================

def _mrz_score(
    ocr_result: Dict[str, Any],
) -> Tuple[float, List[str]]:
    """
    Score MRZ evidence.

    Important:
    MRZ presence strongly suggests a passport/travel document, but MRZ
    presence alone does NOT automatically mean passport.

    We therefore give strong evidence, not absolute certainty.
    """

    score = 0.0
    evidence: List[str] = []

    mrz_found = bool(
        ocr_result.get(
            "mrz_found",
            False,
        )
    )

    if mrz_found:

        score += 55.0

        evidence.append(
            "Machine-readable zone (MRZ) detected"
        )

        checks = ocr_result.get(
            "checks",
            {},
        )

        if isinstance(checks, dict):

            if checks.get(
                "overall_valid"
            ) is True:

                score += 20.0

                evidence.append(
                    "MRZ checksum validation passed"
                )

            elif checks.get(
                "overall_valid"
            ) is False:

                # Failed checksum still indicates MRZ structure,
                # but should not increase document-type confidence
                # as strongly as a valid MRZ.
                score += 5.0

                evidence.append(
                    "MRZ structure detected but checksum validation failed"
                )

    return (
        score,
        evidence,
    )


# ============================================================================
# PASSPORT IDENTIFICATION
# ============================================================================

def _score_passport(
    ocr_result: Dict[str, Any],
    text: str,
) -> Tuple[float, List[str]]:
    """
    Calculate passport-specific evidence.
    """

    score = 0.0
    evidence: List[str] = []

    raw_type = ocr_result.get("document_type")
    explicit_type = str(raw_type).strip().upper() if raw_type else ""

    # If the MRZ type character explicitly designates Visa (V) or National ID (A, C, I),
    # do NOT count MRZ towards passport.
    if explicit_type not in ("V", "A", "C", "I"):
        mrz_score, mrz_evidence = _mrz_score(
            ocr_result
        )

        if mrz_score > 0:
            score += mrz_score
            evidence.extend(
                mrz_evidence
            )
            if explicit_type == "P" or ocr_result.get("mrz_format") == "TD3":
                score += 30.0
                evidence.append("MRZ format/type character indicates passport (P/TD3)")

    # ------------------------------------------------------------------------
    # Explicit passport keywords
    # ------------------------------------------------------------------------

    found = _contains_any(
        text,
        PASSPORT_KEYWORDS,
    )

    if found:

        score += min(
            35.0,
            15.0 * len(found),
        )

        evidence.append(
            "Passport-related keyword(s) detected: "
            + ", ".join(found)
        )

    # ------------------------------------------------------------------------
    # Passport-like fields
    # ------------------------------------------------------------------------

    if _has_field(
        ocr_result,
        "nationality",
    ):

        score += 5.0

        evidence.append(
            "Nationality field detected"
        )

    if _has_field(
        ocr_result,
        "date_of_expiry",
    ):

        score += 5.0

        evidence.append(
            "Expiry date field detected"
        )

    if _has_field(
        ocr_result,
        "document_number",
    ):

        score += 5.0

        evidence.append(
            "Document number field detected"
        )

    return (
        score,
        evidence,
    )


# ============================================================================
# VISA IDENTIFICATION
# ============================================================================

def _score_visa(
    ocr_result: Dict[str, Any],
    text: str,
) -> Tuple[float, List[str]]:
    """
    Calculate visa-specific evidence.
    """

    score = 0.0
    evidence: List[str] = []

    # ------------------------------------------------------------------------
    # Explicit visa fields
    # ------------------------------------------------------------------------

    if _has_field(
        ocr_result,
        "visa_number",
    ):

        score += 45.0

        evidence.append(
            "Visa number field detected"
        )

    if _has_field(
        ocr_result,
        "visa_type",
    ):

        score += 30.0

        evidence.append(
            "Visa type field detected"
        )

    # ------------------------------------------------------------------------
    # Visa keywords
    # ------------------------------------------------------------------------

    found = _contains_any(
        text,
        VISA_KEYWORDS,
    )

    if found:

        score += min(
            45.0,
            20.0 * len(found),
        )

        evidence.append(
            "Visa-related keyword(s) detected: "
            + ", ".join(found)
        )

    # ------------------------------------------------------------------------
    # Visa document type from OCR/MRZ
    # ------------------------------------------------------------------------

    raw_type = ocr_result.get("document_type")
    explicit_type = str(raw_type).strip().upper() if raw_type else ""

    if explicit_type == "V" or explicit_type.startswith("V"):

        score += 60.0

        evidence.append(
            "OCR/MRZ document-type marker indicates visa"
        )

    return (
        score,
        evidence,
    )


# ============================================================================
# DRIVING LICENSE IDENTIFICATION
# ============================================================================

def _score_driving_license(
    ocr_result: Dict[str, Any],
    text: str,
) -> Tuple[float, List[str]]:
    """
    Calculate driving-license-specific evidence.
    """

    score = 0.0
    evidence: List[str] = []

    # ------------------------------------------------------------------------
    # Explicit license class
    # ------------------------------------------------------------------------

    if _has_field(
        ocr_result,
        "license_class",
    ):

        score += 50.0

        evidence.append(
            "Driving-license class field detected"
        )

    # ------------------------------------------------------------------------
    # Driving-license keywords
    # ------------------------------------------------------------------------

    found = _contains_any(
        text,
        DRIVING_LICENSE_KEYWORDS,
    )

    if found:

        score += min(
            60.0,
            45.0 * len(found),
        )

        evidence.append(
            "Driving-license keyword(s) detected: "
            + ", ".join(found)
        )

    # ------------------------------------------------------------------------
    # Typical license fields
    # ------------------------------------------------------------------------

    license_fields = (
        "date_of_issue",
        "date_of_expiry",
        "surname",
        "given_names",
        "document_number",
    )

    field_hits = [
        field
        for field in license_fields
        if _has_field(
            ocr_result,
            field,
        )
    ]

    if len(field_hits) >= 3:

        score += 15.0

        evidence.append(
            "Multiple driving-license-style identity fields detected"
        )

    return (
        score,
        evidence,
    )


# ============================================================================
# NATIONAL ID IDENTIFICATION
# ============================================================================

def _score_national_id(
    ocr_result: Dict[str, Any],
    text: str,
) -> Tuple[float, List[str]]:
    """
    Calculate national-ID-specific evidence.

    This is intentionally conservative.

    Generic fields such as:
        name
        date of birth
        document number

    are NOT enough on their own to confidently identify a national ID,
    because those fields appear on many document types.
    """

    score = 0.0
    evidence: List[str] = []

    raw_type = ocr_result.get("document_type")
    explicit_type = str(raw_type).strip().upper() if raw_type else ""

    if explicit_type in ("A", "C", "I"):
        score += 60.0
        evidence.append(
            f"OCR/MRZ document-type marker indicates national ID ({explicit_type})"
        )

    # ------------------------------------------------------------------------
    # Explicit national-ID keywords
    # ------------------------------------------------------------------------

    found = _contains_any(
        text,
        NATIONAL_ID_KEYWORDS,
    )

    if found:

        score += min(
            60.0,
            30.0 * len(found),
        )

        evidence.append(
            "National-ID keyword(s) detected: "
            + ", ".join(found)
        )

    # ------------------------------------------------------------------------
    # National ID field combinations
    # ------------------------------------------------------------------------

    identity_fields = (
        "document_number",
        "surname",
        "given_names",
        "date_of_birth",
        "nationality",
    )

    field_hits = [
        field
        for field in identity_fields
        if _has_field(
            ocr_result,
            field,
        )
    ]

    # Generic fields are useful supporting evidence only.
    if len(field_hits) >= 5:

        score += 55.0

        evidence.append(
            "All primary national-identity fields detected"
        )

    elif len(field_hits) >= 4:

        score += 20.0

        evidence.append(
            "Multiple national-identity fields detected"
        )

    elif len(field_hits) >= 3:

        score += 10.0

        evidence.append(
            "Several national-identity fields detected"
        )

    return (
        score,
        evidence,
    )


# ============================================================================
# CANDIDATE SCORING
# ============================================================================

def _calculate_candidates(
    ocr_result: Dict[str, Any],
) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
    """
    Calculate scores for every supported document type.
    """

    text = _all_ocr_text(
        ocr_result
    )

    scores: Dict[str, float] = {}
    evidence: Dict[str, List[str]] = {}

    scorers = {
        "passport": _score_passport,
        "visa": _score_visa,
        "driving_license": _score_driving_license,
        "national_id": _score_national_id,
    }

    for doc_type, scorer in scorers.items():

        score, reasons = scorer(
            ocr_result,
            text,
        )

        scores[doc_type] = round(
            max(
                0.0,
                score,
            ),
            2,
        )

        evidence[doc_type] = reasons

    return (
        scores,
        evidence,
    )


# ============================================================================
# CONFIDENCE CALCULATION
# ============================================================================

def _calculate_confidence(
    best_score: float,
    second_score: float,
) -> float:
    """
    Convert candidate score and separation into confidence.

    This is NOT a probability.

    It is a heuristic confidence used for routing decisions.
    """

    if best_score <= 0:
        return 0.0

    # Absolute evidence strength.
    strength = min(
        best_score / 100.0,
        1.0,
    )

    # Separation from competing candidate.
    if best_score > 0:

        separation = (
            best_score - second_score
        ) / best_score

    else:

        separation = 0.0

    separation = max(
        0.0,
        min(
            1.0,
            separation,
        ),
    )

    # Give slightly more importance to actual document evidence
    # than to score separation.
    confidence = (
        (strength * 0.65)
        + (separation * 0.35)
    )

    return round(
        max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        ),
        3,
    )


# ============================================================================
# MAIN IDENTIFICATION FUNCTION
# ============================================================================

def identify_document_type(
    ocr_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Identify the most likely document type.

    Returns
    -------
    {
        "document_type": "passport",
        "confidence": 0.91,
        "evidence": [...],
        "candidate_scores": {
            "passport": 95.0,
            "visa": 0.0,
            "driving_license": 5.0,
            "national_id": 10.0
        }
    }

    Unknown behaviour
    -----------------
    The function returns:

        document_type = "unknown"

    when:

        - no useful evidence exists
        - best score is too low
        - confidence is too low
        - candidates are too close together

    This is intentional.
    """

    if not isinstance(
        ocr_result,
        dict,
    ):

        return {
            "document_type": "unknown",
            "confidence": 0.0,
            "evidence": [
                "Invalid OCR result supplied"
            ],
            "candidate_scores": {},
        }

    scores, candidate_evidence = _calculate_candidates(
        ocr_result
    )

    # ------------------------------------------------------------------------
    # No candidates
    # ------------------------------------------------------------------------

    if not scores:

        return {
            "document_type": "unknown",
            "confidence": 0.0,
            "evidence": [
                "No document-type candidates were generated"
            ],
            "candidate_scores": {},
        }

    # ------------------------------------------------------------------------
    # Rank candidates
    # ------------------------------------------------------------------------

    ranked = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    best_type, best_score = ranked[0]

    if len(ranked) >= 2:

        second_type, second_score = ranked[1]

    else:

        second_type = "unknown"
        second_score = 0.0

    # ------------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------------

    confidence = _calculate_confidence(
        best_score,
        second_score,
    )

    # ------------------------------------------------------------------------
    # Decision gate
    # ------------------------------------------------------------------------

    unknown_reasons: List[str] = []

    if best_score < MIN_IDENTIFICATION_SCORE:

        unknown_reasons.append(
            "No document type produced sufficient identifying evidence"
        )

    if confidence < MIN_IDENTIFICATION_CONFIDENCE:

        unknown_reasons.append(
            "Document-type confidence is below the required threshold"
        )

    if (
        best_score - second_score
    ) < MIN_SCORE_MARGIN:

        unknown_reasons.append(
            (
                f"Top candidates are too close "
                f"({best_type}: {best_score:.1f}, "
                f"{second_type}: {second_score:.1f})"
            )
        )

    # ------------------------------------------------------------------------
    # Unknown
    # ------------------------------------------------------------------------

    if unknown_reasons:

        combined_evidence = [
            "Best candidate was "
            f"'{best_type}' with score {best_score:.1f}"
        ]

        combined_evidence.extend(
            unknown_reasons
        )

        return {
            "document_type": "unknown",
            "confidence": confidence,
            "evidence": combined_evidence,
            "candidate_scores": scores,
        }

    # ------------------------------------------------------------------------
    # Known document
    # ------------------------------------------------------------------------

    evidence = candidate_evidence.get(
        best_type,
        [],
    )

    if not evidence:

        evidence = [
            f"Identified as {best_type}"
        ]

    return {
        "document_type": best_type,
        "confidence": confidence,
        "evidence": evidence,
        "candidate_scores": scores,
    }


# ============================================================================
# COMPATIBILITY ALIAS
# ============================================================================

def classify_document_type(
    ocr_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compatibility alias.

    Some ARGUS modules may use the name `classify_document_type`.
    Keep both names pointing to the same authoritative implementation.
    """

    return identify_document_type(
        ocr_result
    )


# ============================================================================
# SIMPLE SELF-TEST
# ============================================================================

if __name__ == "__main__":

    examples = {

        "passport_example": {
            "mrz_found": True,
            "checks": {
                "overall_valid": True,
            },
            "document_number": "A1234567",
            "nationality": "IND",
            "date_of_birth": "010101",
            "date_of_expiry": "300101",
            "raw_text": "PASSPORT",
        },

        "visa_example": {
            "visa_number": "V123456789",
            "visa_type": "TOURIST",
            "date_of_expiry": "2030-01-01",
            "raw_text": "VISA ENTRY VISA",
        },

        "driving_license_example": {
            "license_class": "LMV",
            "document_number": "DL123456789",
            "surname": "DOE",
            "given_names": "JOHN",
            "date_of_birth": "2000-01-01",
            "date_of_issue": "2025-01-01",
            "date_of_expiry": "2035-01-01",
            "raw_text": "DRIVING LICENCE",
        },

        "national_id_example": {
            "document_number": "123456789012",
            "surname": "DOE",
            "given_names": "JOHN",
            "date_of_birth": "2000-01-01",
            "nationality": "IND",
            "raw_text": "NATIONAL IDENTITY CARD",
        },

        "unknown_example": {
            "raw_text": "Some random text without document identifiers"
        },
    }

    for name, example in examples.items():

        print()
        print("=" * 70)
        print(name)
        print("=" * 70)

        result = identify_document_type(
            example
        )

        print(
            result
        )
# Score margin ensures confident classification between distinct credential types.

"""
ARGUS — Forgery / Fake-Identity Prediction
===========================================

This module performs explainable, rule-based forgery-risk analysis.

It uses evidence from:

    - Document-type identification
    - MRZ checks
    - Date consistency
    - MRZ vs printed-field consistency
    - Blacklist validation
    - Field-format validation
    - Field completeness

It does NOT perform:

    - Pixel-level tampering detection
    - ELA analysis
    - Metadata analysis
    - Face verification
    - Visual forgery classification

Those are handled by other ARGUS modules.

IMPORTANT
---------
Document type is obtained from:

    document_type_identification.py

The old behaviour of:

    "some fields exist -> national_id"

is intentionally removed.

If the document-type classifier cannot identify the document reliably,
the result remains:

    "unknown"

This is important because ARGUS must never invent a document type merely
to make the pipeline produce a classification.

The final numerical risk score is a heuristic risk score, NOT a calibrated
probability that a document is forged.
"""


import re

from datetime import date, datetime
from typing import Optional

from app.modules.document_type_identification import (
    identify_document_type,
)

from app.modules.ocr_extraction import (
    DATE_REGEX,
    _normalize_date as _normalize_free_form_date,
)


# ============================================================================
# POINT WEIGHTS
# ============================================================================

POINTS = {

    # Direct database signal.
    "blacklisted": 40,

    # MRZ checksum failure.
    "mrz_checksum_failed": 25,

    # Passport-style document with no MRZ.
    "mrz_missing_for_passport": 15,

    # Impossible date relationships.
    "date_logic_invalid": 20,

    # MRZ and visible document disagree.
    "mrz_visible_mismatch": 20,

    # Expired document.
    #
    # IMPORTANT:
    # Expired does NOT mean forged.
    # It is only a small risk signal.
    "expired": 10,

    # Invalid document-number format.
    "doc_number_format_invalid": 8,

    # Invalid nationality format.
    #
    # Currently folded into the generic format bucket so one OCR error
    # doesn't get double-penalized.
    "nationality_format_invalid": 7,

    # Missing expected fields.
    #
    # This is deliberately weak because poor OCR can look exactly like
    # missing fields.
    "field_completeness_low": 10,
}


# ============================================================================
# OCR CONFIDENCE
# ============================================================================

LOW_CONFIDENCE_THRESHOLD = 0.40


# ============================================================================
# EXPECTED FIELDS
# ============================================================================

EXPECTED_FIELDS = {

    "passport": {
        "document_number",
        "date_of_birth",
        "date_of_expiry",
        "nationality",
        "sex",
    },

    "visa": {
        "visa_number",
        "visa_type",
        "date_of_expiry",
        "nationality",
    },

    "driving_license": {
        "document_number",
        "surname",
        "given_names",
        "date_of_birth",
        "date_of_issue",
        "date_of_expiry",
        "license_class",
    },

    "national_id": {
        "document_number",
        "surname",
        "given_names",
        "date_of_birth",
        "nationality",
    },

    # UNKNOWN MUST NOT BE PENALIZED FOR MISSING EXPECTED FIELDS.
    "unknown": set(),
}


# ============================================================================
# DOCUMENT NUMBER FORMAT
# ============================================================================

_NATIONALITY_CODE_RE = re.compile(
    r"^[A-Z]{3}$"
)


_ALNUM_DOC_NUMBER_RE = re.compile(
    r"^[A-Z0-9]{5,12}$"
)


# ============================================================================
# DATE PARSING
# ============================================================================

def _parse_date(
    value: Optional[str],
) -> Optional[date]:
    """
    Parse common ARGUS date representations.

    Supported:

        YYYY-MM-DD
        YYMMDD
        DD/MM/YYYY
        MM/DD/YYYY

    Also accepts datetime.date.
    """

    if value is None:
        return None

    if isinstance(
        value,
        date,
    ):
        return value

    value = str(value).strip()

    for fmt in (
        "%Y-%m-%d",
        "%y%m%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ):

        try:

            return datetime.strptime(
                value,
                fmt,
            ).date()

        except ValueError:

            continue

    return None


# ============================================================================
# DATE LOGIC
# ============================================================================

def _check_date_logic(
    ocr_result: dict,
) -> list[str]:
    """
    Check logically impossible date relationships.

    These are strong signals because they are independent of visual
    appearance.

    Examples:

        DOB in future
        impossible age
        issue after expiry
        issue before DOB
    """

    problems = []

    fields = ocr_result.get(
        "fields",
        {},
    )

    if not isinstance(
        fields,
        dict,
    ):
        fields = {}

    # ------------------------------------------------------------------------
    # Date of birth
    # ------------------------------------------------------------------------

    dob = _parse_date(
        ocr_result.get(
            "date_of_birth"
        )
    )

    # ------------------------------------------------------------------------
    # Expiry
    # ------------------------------------------------------------------------

    expiry = _parse_date(
        ocr_result.get(
            "date_of_expiry"
        )
    )

    # ------------------------------------------------------------------------
    # Issue date
    # ------------------------------------------------------------------------

    raw_issue = fields.get(
        "date_of_issue"
    )

    issue = None

    if raw_issue:

        normalized_issue = _normalize_free_form_date(
            raw_issue
        )

        issue = _parse_date(
            normalized_issue
        )

    today = date.today()

    # ------------------------------------------------------------------------
    # Future DOB
    # ------------------------------------------------------------------------

    if dob and dob > today:

        problems.append(
            f"Date of birth ({dob.isoformat()}) "
            "is in the future"
        )

    # ------------------------------------------------------------------------
    # Implausible age
    # ------------------------------------------------------------------------

    if dob:

        age = (
            today.year
            - dob.year
            - (
                (today.month, today.day)
                <
                (dob.month, dob.day)
            )
        )

        if age > 115:

            problems.append(
                f"Date of birth ({dob.isoformat()}) "
                "implies an implausible age"
            )

    # ------------------------------------------------------------------------
    # Issue after expiry
    # ------------------------------------------------------------------------

    if (
        issue
        and expiry
        and issue > expiry
    ):

        problems.append(
            f"Date of issue ({issue.isoformat()}) "
            f"is after date of expiry ({expiry.isoformat()})"
        )

    # ------------------------------------------------------------------------
    # Issue before DOB
    # ------------------------------------------------------------------------

    if (
        dob
        and issue
        and issue < dob
    ):

        problems.append(
            f"Date of issue ({issue.isoformat()}) "
            f"is before date of birth ({dob.isoformat()})"
        )

    return problems


# ============================================================================
# FORMAT VALIDATION
# ============================================================================

def _check_formats(
    ocr_result: dict,
) -> list[str]:
    """
    Check simple structural formats.

    These are soft signals.

    They should NOT by themselves prove forgery.
    """

    problems = []

    # ------------------------------------------------------------------------
    # Nationality
    # ------------------------------------------------------------------------

    nationality = ocr_result.get(
        "nationality"
    )

    if (
        nationality
        and ocr_result.get("mrz_found")
    ):

        nationality_clean = (
            str(nationality)
            .strip()
            .upper()
        )

        if not _NATIONALITY_CODE_RE.match(
            nationality_clean
        ):

            problems.append(
                f"Nationality code '{nationality}' "
                "is not a valid 3-letter code"
            )

    # ------------------------------------------------------------------------
    # Document number
    # ------------------------------------------------------------------------

    doc_number = ocr_result.get(
        "document_number"
    )

    if doc_number:

        doc_number_clean = (
            str(doc_number)
            .strip()
            .upper()
        )

        if not _ALNUM_DOC_NUMBER_RE.match(
            doc_number_clean
        ):

            problems.append(
                f"Document number '{doc_number}' "
                "does not match expected format"
            )

    return problems


# ============================================================================
# NAME NORMALIZATION
# ============================================================================

def _normalize_name_text(
    value: Optional[str],
) -> Optional[str]:
    """
    Normalize a name for MRZ/printed-text comparison.
    """

    if not value:
        return None

    cleaned = re.sub(
        r"[^A-Z ]",
        "",
        str(value).upper(),
    ).strip()

    return cleaned or None


# ============================================================================
# MRZ DATE PARSING
# ============================================================================

def _parse_mrz_yymmdd(
    value: Optional[str],
) -> Optional[str]:
    """
    Convert MRZ YYMMDD into ISO YYYY-MM-DD.

    Python's %y handling is intentionally used consistently with the rest
    of ARGUS.
    """

    if not value:
        return None

    try:

        return datetime.strptime(
            str(value),
            "%y%m%d",
        ).date().isoformat()

    except ValueError:

        return None


# ============================================================================
# MRZ VS VISIBLE DOCUMENT CONSISTENCY
# ============================================================================

def _check_mrz_visible_consistency(
    ocr_result: dict,
) -> list[str]:
    """
    Compare MRZ-derived values against printed-page OCR.

    This is only performed when MRZ exists.

    Comparisons:

        surname
        given names
        document number
        date of birth
        date of expiry

    Nationality is intentionally not compared because:

        MRZ -> 3-letter ISO code
        Printed document -> often full country name/demonym

    Example:

        IND
        INDIAN

    requires a proper country mapping table.
    """

    if not ocr_result.get(
        "mrz_found"
    ):

        return []

    fields = ocr_result.get(
        "fields",
        {},
    )

    if not isinstance(
        fields,
        dict,
    ):

        fields = {}

    mismatches = []

    # =========================================================================
    # SURNAME
    # =========================================================================

    mrz_surname = _normalize_name_text(
        ocr_result.get(
            "surname"
        )
    )

    printed_surname = _normalize_name_text(
        fields.get(
            "surname"
        )
    )

    if (
        mrz_surname
        and printed_surname
        and mrz_surname != printed_surname
    ):

        mismatches.append(
            f"Surname on MRZ ('{ocr_result.get('surname')}') "
            f"does not match printed field "
            f"('{fields.get('surname')}')"
        )

    # =========================================================================
    # GIVEN NAMES
    # =========================================================================

    mrz_given = _normalize_name_text(
        ocr_result.get(
            "given_names"
        )
    )

    printed_given = _normalize_name_text(
        fields.get(
            "given_names"
        )
    )

    if (
        mrz_given
        and printed_given
        and mrz_given != printed_given
    ):

        mismatches.append(
            f"Given names on MRZ ('{ocr_result.get('given_names')}') "
            f"do not match printed field "
            f"('{fields.get('given_names')}')"
        )

    # =========================================================================
    # DOCUMENT NUMBER
    # =========================================================================

    checks = ocr_result.get(
        "checks",
        {},
    )

    if not isinstance(
        checks,
        dict,
    ):

        checks = {}

    mrz_doc_number = ocr_result.get(
        "document_number"
    )

    printed_doc_number = fields.get(
        "document_number"
    )

    # Only compare if MRZ document-number checksum is valid.
    if (
        checks.get(
            "document_number_valid",
            True,
        )
        and mrz_doc_number
        and printed_doc_number
    ):

        mrz_clean = re.sub(
            r"[^A-Z0-9]",
            "",
            str(mrz_doc_number).upper(),
        )

        printed_clean = re.sub(
            r"[^A-Z0-9]",
            "",
            str(printed_doc_number).upper(),
        )

        if (
            mrz_clean
            and printed_clean
            and mrz_clean != printed_clean
        ):

            mismatches.append(
                f"Document number on MRZ "
                f"('{mrz_doc_number}') does not match "
                f"printed field "
                f"('{printed_doc_number}')"
            )

    # =========================================================================
    # DATES
    # =========================================================================

    date_comparisons = (

        (
            "date_of_birth",
            "date_of_birth",
            "Date of birth",
        ),

        (
            "date_of_expiry",
            "date_of_expiry",
            "Date of expiry",
        ),

    )

    for (
        mrz_key,
        printed_key,
        label,
    ) in date_comparisons:

        printed_raw = fields.get(
            printed_key
        )

        if not printed_raw:

            continue

        printed_raw = str(
            printed_raw
        ).strip()

        # Do not compare incomplete OCR captures.
        if not DATE_REGEX.fullmatch(
            printed_raw
        ):

            continue

        printed_normalized = (
            _normalize_free_form_date(
                printed_raw
            )
        )

        mrz_normalized = _parse_mrz_yymmdd(
            ocr_result.get(
                mrz_key
            )
        )

        if (
            printed_normalized
            and mrz_normalized
            and printed_normalized != mrz_normalized
        ):

            mismatches.append(
                f"{label} on MRZ "
                f"('{mrz_normalized}') does not match "
                f"printed field "
                f"('{printed_normalized}')"
            )

    return mismatches


# ============================================================================
# FIELD COMPLETENESS
# ============================================================================

def _field_completeness(
    ocr_result: dict,
    doc_type: str,
) -> float:
    """
    Calculate the fraction of expected fields that were extracted.

    This is deliberately a weak signal.

    Missing OCR fields can mean:

        - bad scan
        - poor lighting
        - unusual layout
        - unsupported document
        - OCR failure

    It does NOT automatically mean forgery.
    """

    expected = EXPECTED_FIELDS.get(
        doc_type,
        set(),
    )

    # Unknown document types have no known field schema.
    if not expected:

        return 1.0

    # ------------------------------------------------------------------------
    # MRZ documents
    # ------------------------------------------------------------------------

    if ocr_result.get(
        "mrz_found"
    ):

        present = {
            field
            for field in expected
            if ocr_result.get(field)
        }

        return (
            len(present)
            / len(expected)
        )

    # ------------------------------------------------------------------------
    # Non-MRZ documents
    # ------------------------------------------------------------------------

    fields = ocr_result.get(
        "fields",
        {},
    )

    if not isinstance(
        fields,
        dict,
    ):

        fields = {}

    field_confidence = ocr_result.get(
        "field_confidence",
        {},
    )

    if not isinstance(
        field_confidence,
        dict,
    ):

        field_confidence = {}

    present = set()

    for field in expected:

        value = (
            fields.get(field)
            or ocr_result.get(field)
        )

        confidence = _safe_float(
            field_confidence.get(
                field,
                1.0,
            ),
            1.0,
        )

        if (
            value
            and confidence >= LOW_CONFIDENCE_THRESHOLD
        ):

            present.add(
                field
            )

    return (
        len(present)
        / len(expected)
    )


# ============================================================================
# DOCUMENT TYPE IDENTIFICATION
# ============================================================================

def _identify_type(
    ocr_result: dict,
) -> dict:
    """
    Run the dedicated document-type identification module.

    Kept as a helper so this module has one clear integration point.
    """

    try:

        result = identify_document_type(
            ocr_result
        )

        if not isinstance(
            result,
            dict,
        ):

            return {
                "document_type": "unknown",
                "confidence": 0.0,
                "evidence": [
                    "Document-type classifier returned invalid output"
                ],
                "candidate_scores": {},
            }

        return result

    except Exception as exc:

        # The forgery module must fail conservatively.

        return {
            "document_type": "unknown",
            "confidence": 0.0,
            "evidence": [
                (
                    "Document-type identification failed: "
                    f"{type(exc).__name__}"
                )
            ],
            "candidate_scores": {},
        }


# ============================================================================
# MAIN FORGERY PREDICTION
# ============================================================================

def predict_forgery(
    ocr_result: dict,
    validation_result: dict,
) -> dict:
    """
    Calculate explainable rule-based forgery risk.

    Parameters
    ----------
    ocr_result:
        Output from OCR/document extraction.

    validation_result:
        Output from document_validation.py.

    Returns
    -------
    dict

    Example:

        {
            "document_type_guess": "passport",
            "document_type_confidence": 0.94,
            "document_type_evidence": [...],
            "document_type_candidates": {...},
            "forgery_risk_score": 18.0,
            "label": "LIKELY_AUTHENTIC",
            "triggered_signals": {...},
            "reasons": [...],
            "field_completeness": 0.8
        }
    """

    if not isinstance(
        ocr_result,
        dict,
    ):

        ocr_result = {}

    if not isinstance(
        validation_result,
        dict,
    ):

        validation_result = {}

    # =========================================================================
    # 1. DOCUMENT TYPE
    # =========================================================================

    type_result = _identify_type(
        ocr_result
    )

    doc_type = type_result.get(
        "document_type",
        "unknown",
    )

    if doc_type not in EXPECTED_FIELDS:

        doc_type = "unknown"

    doc_type_confidence = _safe_float(
        type_result.get(
            "confidence",
            0.0,
        ),
        0.0,
    )

    doc_type_confidence = max(
        0.0,
        min(
            1.0,
            doc_type_confidence,
        ),
    )

    doc_type_evidence = type_result.get(
        "evidence",
        [],
    )

    if not isinstance(
        doc_type_evidence,
        list,
    ):

        doc_type_evidence = []

    candidate_scores = type_result.get(
        "candidate_scores",
        {},
    )

    if not isinstance(
        candidate_scores,
        dict,
    ):

        candidate_scores = {}

    # =========================================================================
    # 2. INITIALIZE
    # =========================================================================

    reasons = []

    points = 0.0

    triggered = {}

    # =========================================================================
    # 3. BLACKLIST
    # =========================================================================

    if validation_result.get(
        "is_blacklisted"
    ):

        points += POINTS[
            "blacklisted"
        ]

        triggered[
            "blacklisted"
        ] = True

        reasons.append(
            "Document number matches a blacklist entry"
        )

    # =========================================================================
    # 4. MRZ CHECKSUM
    # =========================================================================

    if ocr_result.get(
        "mrz_found"
    ):

        checks = ocr_result.get(
            "checks",
            {},
        )

        if not isinstance(
            checks,
            dict,
        ):

            checks = {}

        if (
            checks
            and not checks.get(
                "overall_valid",
                True,
            )
        ):

            points += POINTS[
                "mrz_checksum_failed"
            ]

            triggered[
                "mrz_checksum_failed"
            ] = True

            failed = [
                key
                for key, value in checks.items()
                if not value
                and key != "overall_valid"
            ]

            mrz_conf = ocr_result.get(
                "mrz_ocr_confidence"
            )

            conf_note = ""

            if mrz_conf is not None:

                mrz_conf = _safe_float(
                    mrz_conf,
                    0.0,
                )

                if mrz_conf < LOW_CONFIDENCE_THRESHOLD:

                    conf_note = (
                        f" [MRZ OCR confidence: "
                        f"{mrz_conf:.0%} - low, OCR "
                        "misread is a plausible explanation; "
                        "consider re-scanning]"
                    )

                else:

                    conf_note = (
                        f" [MRZ OCR confidence: "
                        f"{mrz_conf:.0%} - reasonably high]"
                    )

            reasons.append(
                (
                    "MRZ checksum validation failed "
                    f"({', '.join(failed) or 'overall'})"
                    f"{conf_note}"
                )
            )

    # =========================================================================
    # 5. PASSPORT WITHOUT MRZ
    # =========================================================================

    elif (
        doc_type == "passport"
    ):

        points += POINTS[
            "mrz_missing_for_passport"
        ]

        triggered[
            "mrz_missing_for_passport"
        ] = True

        reasons.append(
            "No MRZ detected on a document "
            "identified as passport-style"
        )

    # =========================================================================
    # 6. DATE LOGIC
    # =========================================================================

    date_problems = _check_date_logic(
        ocr_result
    )

    if date_problems:

        points += POINTS[
            "date_logic_invalid"
        ]

        triggered[
            "date_logic_invalid"
        ] = True

        reasons.extend(
            date_problems
        )

    # =========================================================================
    # 7. MRZ VS PRINTED PAGE
    # =========================================================================

    mismatches = _check_mrz_visible_consistency(
        ocr_result
    )

    if mismatches:

        points += POINTS[
            "mrz_visible_mismatch"
        ]

        triggered[
            "mrz_visible_mismatch"
        ] = True

        reasons.extend(
            mismatches
        )

    # =========================================================================
    # 8. EXPIRY
    # =========================================================================

    if validation_result.get(
        "is_expired"
    ):

        points += POINTS[
            "expired"
        ]

        triggered[
            "expired"
        ] = True

        reasons.append(
            "Document is expired"
        )

    # =========================================================================
    # 9. FORMAT VALIDATION
    # =========================================================================

    format_problems = _check_formats(
        ocr_result
    )

    if format_problems:

        # Keep this as one score bucket.
        #
        # This prevents multiple OCR mistakes from artificially stacking
        # large amounts of risk.

        points += POINTS[
            "doc_number_format_invalid"
        ]

        triggered[
            "format_invalid"
        ] = True

        reasons.extend(
            format_problems
        )

    # =========================================================================
    # 10. FIELD COMPLETENESS
    # =========================================================================

    completeness = _field_completeness(
        ocr_result,
        doc_type,
    )

    completeness = max(
        0.0,
        min(
            1.0,
            completeness,
        ),
    )

    if completeness < 0.60:

        points += POINTS[
            "field_completeness_low"
        ]

        triggered[
            "field_completeness_low"
        ] = True

        if doc_type == "unknown":

            reasons.append(
                (
                    "Document type is unknown; "
                    "document-specific field completeness "
                    "could not be evaluated"
                )
            )

        else:

            reasons.append(
                (
                    f"Only {completeness:.0%} of expected fields "
                    f"for a {doc_type.replace('_', ' ')} "
                    "were extracted"
                )
            )

    # =========================================================================
    # 11. UNKNOWN DOCUMENT TYPE
    # =========================================================================
    #
    # UNKNOWN IS NOT ITSELF PROOF OF FORGERY.
    #
    # It is primarily an evidence-quality issue and should be handled by
    # evidence_quality.py / risk_engine.py.
    #
    # Therefore we do NOT add arbitrary forgery points here.
    #

    if doc_type == "unknown":

        triggered[
            "document_type_unknown"
        ] = True

        reasons.append(
            "Document type could not be identified reliably"
        )

    # =========================================================================
    # 12. SCORE
    # =========================================================================

    score = min(
        round(
            points,
            1,
        ),
        100.0,
    )

    # =========================================================================
    # 13. LABEL
    # =========================================================================

    if score < 20:

        label = "LIKELY_AUTHENTIC"

    elif score < 50:

        label = "SUSPICIOUS"

    else:

        label = "LIKELY_FORGED"

    # =========================================================================
    # 14. BLACKLIST OVERRIDE
    # =========================================================================
    #
    # A confirmed blacklist hit is a direct database fact.
    #
    # It should not be diluted into "SUSPICIOUS".
    #

    if triggered.get(
        "blacklisted"
    ):

        score = max(
            score,
            90.0,
        )

        label = "LIKELY_FORGED"

    # =========================================================================
    # 15. RETURN
    # =========================================================================

    return {

        # ---------------------------------------------------------------------
        # Document type
        # ---------------------------------------------------------------------

        "document_type_guess": doc_type,

        "document_type_confidence": round(
            doc_type_confidence,
            3,
        ),

        "document_type_evidence": doc_type_evidence,

        "document_type_candidates": candidate_scores,

        # ---------------------------------------------------------------------
        # Forgery score
        # ---------------------------------------------------------------------

        "forgery_risk_score": score,

        "label": label,

        # ---------------------------------------------------------------------
        # Triggered signals
        # ---------------------------------------------------------------------

        "triggered_signals": triggered,

        # ---------------------------------------------------------------------
        # Human-readable reasons
        # ---------------------------------------------------------------------

        "reasons": reasons,

        # ---------------------------------------------------------------------
        # Completeness
        # ---------------------------------------------------------------------

        "field_completeness": round(
            completeness,
            3,
        ),
    }
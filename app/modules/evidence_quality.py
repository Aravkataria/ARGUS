"""
ARGUS — Evidence Quality Assessment
====================================

Determines whether ARGUS has enough reliable evidence to make a
document-authenticity decision.

IMPORTANT
---------
Evidence quality is NOT the same thing as forgery probability.

A document can have:

    Visual model = 96% authentic
    Evidence quality = 70%

and still be:

    INCONCLUSIVE

because the available evidence is not reliable enough.

This module evaluates:

    1. Document-type identification
    2. Document-type confidence
    3. OCR field extraction
    4. OCR field confidence
    5. MRZ availability
    6. MRZ validation
    7. Critical identity fields
    8. Validation coverage
    9. Visual-model confidence
   10. Tampering-analysis availability
   11. Face-verification availability

The final risk engine uses this module as a HARD decision gate.

This module intentionally does NOT decide:

    AUTHENTIC
    FORGED
    SUSPICIOUS

It only answers:

    "Do we have enough trustworthy evidence to make that decision?"
"""

from typing import Any, Dict, List


# ============================================================================
# THRESHOLDS
# ============================================================================

# Minimum overall evidence quality required for a confident decision.
MIN_DECISION_EVIDENCE = 0.75

# Below this, evidence is considered poor.
MIN_MEDIUM_EVIDENCE = 0.50

# OCR confidence below this is considered unreliable.
LOW_OCR_CONFIDENCE = 0.40

# OCR confidence considered strong.
HIGH_OCR_CONFIDENCE = 0.80

# Document-type confidence thresholds.
MIN_DOCUMENT_TYPE_CONFIDENCE = 0.60
STRONG_DOCUMENT_TYPE_CONFIDENCE = 0.80


# ============================================================================
# FIELD DEFINITIONS
# ============================================================================

# Fields that are useful across many identity documents.
GENERAL_CRITICAL_FIELDS = {
    "document_number",
    "date_of_birth",
}

# Additional fields commonly found on specific documents.
EXPECTED_FIELDS = {

    "passport": {
        "document_number",
        "surname",
        "given_names",
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

    "unknown": set(),
}


# ============================================================================
# HELPERS
# ============================================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """
    Safely convert a value to float.
    """

    try:

        if value is None:
            return default

        return float(value)

    except (TypeError, ValueError):

        return default


def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    """
    Clamp a value to [minimum, maximum].
    """

    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


def _normalise_probability(
    value: Any,
) -> float:
    """
    Convert a probability-like value into [0, 1].

    Supports both:

        0.96
        96
    """

    value = _safe_float(
        value,
        0.0,
    )

    if value > 1.0:

        value /= 100.0

    return _clamp(
        value
    )


def _append_unique(
    items: List[str],
    value: str,
) -> None:
    """
    Append a string only once.
    """

    if not value:
        return

    value = str(value)

    if value not in items:

        items.append(
            value
        )


def _get_document_type(
    ocr_result: Dict[str, Any],
) -> str:
    """
    Extract document type from the output of document-type identification.

    Supports both:

        document_type = {
            "document_type": "passport",
            ...
        }

    and older/simple structures where document_type itself is a string.
    """

    document_type = ocr_result.get(
        "document_type"
    )

    if isinstance(
        document_type,
        dict,
    ):

        value = document_type.get(
            "document_type"
        )

        if value:

            return str(value).strip().lower()

    elif isinstance(
        document_type,
        str,
    ):

        return document_type.strip().lower()

    return "unknown"


def _get_document_type_confidence(
    ocr_result: Dict[str, Any],
) -> float:
    """
    Extract document-type confidence.
    """

    document_type = ocr_result.get(
        "document_type"
    )

    if isinstance(
        document_type,
        dict,
    ):

        return _normalise_probability(
            document_type.get(
                "confidence",
                0.0,
            )
        )

    return 0.0


def _get_fields(
    ocr_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Safely obtain OCR fields.
    """

    fields = ocr_result.get(
        "fields",
        {}
    )

    if not isinstance(
        fields,
        dict,
    ):

        return {}

    return fields


def _get_field_confidence(
    ocr_result: Dict[str, Any],
) -> Dict[str, float]:
    """
    Safely obtain OCR field confidence values.
    """

    confidence = ocr_result.get(
        "field_confidence",
        {}
    )

    if not isinstance(
        confidence,
        dict,
    ):

        return {}

    return {
        str(key): _normalise_probability(value)
        for key, value in confidence.items()
    }


def _get_field_value(
    ocr_result: Dict[str, Any],
    field_name: str,
) -> Any:
    """
    Get a field from either:

        top-level OCR output

    or:

        OCR output["fields"]
    """

    if field_name in ocr_result:

        value = ocr_result.get(
            field_name
        )

        if value not in (
            None,
            "",
        ):

            return value

    fields = _get_fields(
        ocr_result
    )

    return fields.get(
        field_name
    )


def _field_is_present(
    ocr_result: Dict[str, Any],
    field_name: str,
) -> bool:
    """
    Determine whether a field contains usable data.
    """

    value = _get_field_value(
        ocr_result,
        field_name,
    )

    if value is None:
        return False

    if isinstance(
        value,
        str,
    ):

        return bool(
            value.strip()
        )

    return True


def _field_is_reliable(
    ocr_result: Dict[str, Any],
    field_name: str,
) -> bool:
    """
    Determine whether an extracted field has sufficient OCR confidence.

    MRZ-derived fields are treated as reliable when the MRZ exists and
    the relevant checksum is valid, because MRZ validation provides
    stronger evidence than raw OCR confidence.
    """

    if not _field_is_present(
        ocr_result,
        field_name,
    ):

        return False

    # ------------------------------------------------------------------------
    # MRZ evidence
    # ------------------------------------------------------------------------

    mrz_found = bool(
        ocr_result.get(
            "mrz_found",
            False,
        )
    )

    if mrz_found:

        checks = ocr_result.get(
            "checks",
            {}
        )

        if isinstance(
            checks,
            dict,
        ):

            # Document number has a dedicated checksum.
            if field_name == "document_number":

                if checks.get(
                    "document_number_valid"
                ) is True:

                    return True

            # DOB has a dedicated MRZ checksum on standard TD3/TD1 MRZ.
            if field_name == "date_of_birth":

                if checks.get(
                    "date_of_birth_valid"
                ) is True:

                    return True

            # Expiry similarly has a checksum.
            if field_name == "date_of_expiry":

                if checks.get(
                    "date_of_expiry_valid"
                ) is True:

                    return True

            # If the entire MRZ is valid, MRZ-derived fields receive
            # reasonable trust even when an individual check isn't surfaced.
            if checks.get(
                "overall_valid"
            ) is True:

                return True

    # ------------------------------------------------------------------------
    # Normal OCR confidence
    # ------------------------------------------------------------------------

    confidence = _get_field_confidence(
        ocr_result
    )

    # If confidence isn't supplied, presence alone is weak evidence.
    field_conf = confidence.get(
        field_name,
        0.0,
    )

    return field_conf >= LOW_OCR_CONFIDENCE


# ============================================================================
# DOCUMENT TYPE QUALITY
# ============================================================================

def _evaluate_document_type(
    ocr_result: Dict[str, Any],
    reasons: List[str],
    positive_evidence: List[str],
) -> Dict[str, Any]:
    """
    Evaluate document-type identification quality.
    """

    document_type = _get_document_type(
        ocr_result
    )

    confidence = _get_document_type_confidence(
        ocr_result
    )

    # ------------------------------------------------------------------------
    # Unknown document
    # ------------------------------------------------------------------------

    if (
        not document_type
        or document_type == "unknown"
    ):

        _append_unique(
            reasons,
            "Document type could not be identified reliably",
        )

        return {
            "document_type": "unknown",
            "confidence": confidence,
            "quality": 0.0,
        }

    # ------------------------------------------------------------------------
    # Strong identification
    # ------------------------------------------------------------------------

    if confidence >= STRONG_DOCUMENT_TYPE_CONFIDENCE:

        quality = 1.0

        _append_unique(
            positive_evidence,
            (
                f"Document type identified as "
                f"{document_type.replace('_', ' ')} "
                f"with strong confidence ({confidence:.0%})"
            ),
        )

    # ------------------------------------------------------------------------
    # Moderate identification
    # ------------------------------------------------------------------------

    elif confidence >= MIN_DOCUMENT_TYPE_CONFIDENCE:

        quality = 0.70

        _append_unique(
            reasons,
            (
                f"Document type identified as "
                f"{document_type.replace('_', ' ')} "
                f"with moderate confidence ({confidence:.0%})"
            ),
        )

    # ------------------------------------------------------------------------
    # Weak identification
    # ------------------------------------------------------------------------

    else:

        quality = 0.30

        _append_unique(
            reasons,
            (
                f"Document type identification confidence is low "
                f"({confidence:.0%})"
            ),
        )

    return {
        "document_type": document_type,
        "confidence": confidence,
        "quality": quality,
    }


# ============================================================================
# OCR QUALITY
# ============================================================================

def _evaluate_ocr_quality(
    ocr_result: Dict[str, Any],
    document_type: str,
    reasons: List[str],
    positive_evidence: List[str],
) -> Dict[str, Any]:
    """
    Evaluate OCR extraction quality.
    """

    fields = _get_fields(
        ocr_result
    )

    confidences = _get_field_confidence(
        ocr_result
    )

    expected = EXPECTED_FIELDS.get(
        document_type,
        set(),
    )

    # ------------------------------------------------------------------------
    # Collect available field confidences.
    # ------------------------------------------------------------------------

    usable_confidences = []

    very_low_confidence_fields = []

    for field_name, confidence in confidences.items():

        if not _field_is_present(
            ocr_result,
            field_name,
        ):

            continue

        usable_confidences.append(
            confidence
        )

        if confidence < LOW_OCR_CONFIDENCE:

            very_low_confidence_fields.append(
                field_name
            )

    # ------------------------------------------------------------------------
    # Average OCR confidence.
    # ------------------------------------------------------------------------

    if usable_confidences:

        average_confidence = (
            sum(usable_confidences)
            / len(usable_confidences)
        )

    else:

        average_confidence = 0.0

    # ------------------------------------------------------------------------
    # Expected-field completeness.
    # ------------------------------------------------------------------------

    if expected:

        present_fields = 0

        for field_name in expected:

            if _field_is_reliable(
                ocr_result,
                field_name,
            ):

                present_fields += 1

        completeness = (
            present_fields
            / len(expected)
        )

    else:

        # Unknown document type cannot be judged against a fake checklist.
        completeness = 0.0

    # ------------------------------------------------------------------------
    # No OCR fields at all.
    # ------------------------------------------------------------------------

    if not fields and not confidences:

        _append_unique(
            reasons,
            "No reliable OCR fields were extracted",
        )

    # ------------------------------------------------------------------------
    # Very low average confidence.
    # ------------------------------------------------------------------------

    elif average_confidence < LOW_OCR_CONFIDENCE:

        _append_unique(
            reasons,
            (
                "OCR field confidence is very low "
                f"(average {average_confidence:.0%})"
            ),
        )

    # ------------------------------------------------------------------------
    # Moderate average confidence.
    # ------------------------------------------------------------------------

    elif average_confidence < HIGH_OCR_CONFIDENCE:

        _append_unique(
            reasons,
            (
                "OCR field confidence is moderate "
                f"(average {average_confidence:.0%})"
            ),
        )

    else:

        _append_unique(
            positive_evidence,
            (
                "OCR fields have strong average confidence "
                f"({average_confidence:.0%})"
            ),
        )

    # ------------------------------------------------------------------------
    # Very-low-confidence fields.
    # ------------------------------------------------------------------------

    if very_low_confidence_fields:

        _append_unique(
            reasons,
            (
                f"{len(very_low_confidence_fields)} extracted field(s) "
                "have very low confidence"
            ),
        )

    # ------------------------------------------------------------------------
    # Completeness.
    # ------------------------------------------------------------------------

    if expected:

        if completeness < 0.40:

            _append_unique(
                reasons,
                (
                    f"Only {completeness:.0%} of expected "
                    f"{document_type.replace('_', ' ')} fields "
                    "were reliably extracted"
                ),
            )

        elif completeness < 0.70:

            _append_unique(
                reasons,
                (
                    f"Field extraction is incomplete "
                    f"({completeness:.0%} of expected fields)"
                ),
            )

        else:

            _append_unique(
                positive_evidence,
                (
                    f"{completeness:.0%} of expected document fields "
                    "were reliably extracted"
                ),
            )

    # ------------------------------------------------------------------------
    # OCR quality score.
    # ------------------------------------------------------------------------

    confidence_component = average_confidence

    completeness_component = completeness

    # For unknown document types, don't punish completeness twice.
    if not expected:

        ocr_quality = confidence_component

    else:

        ocr_quality = (
            (confidence_component * 0.60)
            + (completeness_component * 0.40)
        )

    return {
        "average_confidence": round(
            average_confidence,
            3,
        ),
        "completeness": round(
            completeness,
            3,
        ),
        "quality": round(
            _clamp(ocr_quality),
            3,
        ),
        "very_low_confidence_fields": (
            very_low_confidence_fields
        ),
    }


# ============================================================================
# MRZ QUALITY
# ============================================================================

def _evaluate_mrz(
    ocr_result: Dict[str, Any],
    reasons: List[str],
    positive_evidence: List[str],
) -> Dict[str, Any]:
    """
    Evaluate MRZ evidence.

    MRZ is strong evidence when:

        - it exists
        - checksum validation succeeds

    Missing MRZ is NOT automatically forgery.
    """

    mrz_found = bool(
        ocr_result.get(
            "mrz_found",
            False,
        )
    )

    if not mrz_found:

        _append_unique(
            reasons,
            "No MRZ found",
        )

        return {
            "found": False,
            "valid": False,
            "quality": 0.0,
        }

    checks = ocr_result.get(
        "checks",
        {}
    )

    if not isinstance(
        checks,
        dict,
    ):

        checks = {}

    overall_valid = checks.get(
        "overall_valid"
    )

    # ------------------------------------------------------------------------
    # Valid MRZ
    # ------------------------------------------------------------------------

    if overall_valid is True:

        _append_unique(
            positive_evidence,
            "MRZ detected and checksum validation passed",
        )

        return {
            "found": True,
            "valid": True,
            "quality": 1.0,
        }

    # ------------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------------

    check_values = [
        value
        for key, value in checks.items()
        if key != "overall_valid"
        and isinstance(value, bool)
    ]

    if check_values:

        passed = sum(
            1
            for value in check_values
            if value
        )

        quality = (
            passed
            / len(check_values)
        )

    else:

        quality = 0.50

    if quality < 0.50:

        _append_unique(
            reasons,
            "MRZ was detected but validation checks failed",
        )

    else:

        _append_unique(
            reasons,
            (
                "MRZ detected but checksum validation "
                "is incomplete or partially failed"
            ),
        )

    return {
        "found": True,
        "valid": False,
        "quality": round(
            quality,
            3,
        ),
    }


# ============================================================================
# VALIDATION QUALITY
# ============================================================================

def _evaluate_validation(
    validation: Dict[str, Any],
    reasons: List[str],
    positive_evidence: List[str],
) -> Dict[str, Any]:
    """
    Evaluate document-validation evidence.

    Validation coverage is different from forgery risk.

    Example:

        validity_ratio = 1.0

    does NOT mean:

        document is authentic

    It means:

        all available validation checks passed.
    """

    if not isinstance(
        validation,
        dict,
    ):

        return {
            "quality": 0.0,
            "coverage": 0.0,
        }

    checks_total = int(
        _safe_float(
            validation.get(
                "checks_total",
                0,
            ),
            0.0,
        )
    )

    checks_passed = int(
        _safe_float(
            validation.get(
                "checks_passed",
                0,
            ),
            0.0,
        )
    )

    validity_ratio = _normalise_probability(
        validation.get(
            "validity_ratio",
            0.0,
        )
    )

    # ------------------------------------------------------------------------
    # No validation checks.
    # ------------------------------------------------------------------------

    if checks_total <= 0:

        _append_unique(
            reasons,
            "No document-validation checks were available",
        )

        return {
            "quality": 0.0,
            "coverage": 0.0,
        }

    coverage = 1.0

    # ------------------------------------------------------------------------
    # All checks passed.
    # ------------------------------------------------------------------------

    if validity_ratio >= 0.999:

        _append_unique(
            positive_evidence,
            (
                f"Document validation checks passed "
                f"({checks_passed}/{checks_total})"
            ),
        )

    # ------------------------------------------------------------------------
    # Partial failures.
    # ------------------------------------------------------------------------

    elif validity_ratio >= 0.50:

        _append_unique(
            reasons,
            (
                f"Some document validation checks failed "
                f"({checks_passed}/{checks_total} passed)"
            ),
        )

    else:

        _append_unique(
            reasons,
            (
                f"Most document validation checks failed "
                f"({checks_passed}/{checks_total} passed)"
            ),
        )

    return {
        "quality": round(
            validity_ratio,
            3,
        ),
        "coverage": coverage,
    }


# ============================================================================
# VISUAL MODEL QUALITY
# ============================================================================

def _evaluate_visual_model(
    forgery: Dict[str, Any],
    reasons: List[str],
    positive_evidence: List[str],
) -> Dict[str, Any]:
    """
    Evaluate whether the visual model provides useful confidence.

    This measures MODEL EVIDENCE QUALITY.

    It does NOT assume the model is correct.
    """

    if not isinstance(
        forgery,
        dict,
    ):

        return {
            "available": False,
            "confidence": 0.0,
            "quality": 0.0,
        }

    visual = forgery.get(
        "visual_model",
        {}
    )

    if not isinstance(
        visual,
        dict,
    ):

        # Backward-compatible direct structure.
        visual = forgery

    authentic = _normalise_probability(
        visual.get(
            "authentic_probability",
            0.0,
        )
    )

    forged = _normalise_probability(
        visual.get(
            "forged_probability",
            0.0,
        )
    )

    if authentic <= 0.0 and forged <= 0.0:

        _append_unique(
            reasons,
            "Visual forgery model did not provide usable probabilities",
        )

        return {
            "available": False,
            "confidence": 0.0,
            "quality": 0.0,
        }

    # The model's confidence is the larger class probability.
    confidence = max(
        authentic,
        forged,
    )

    if confidence >= 0.90:

        quality = 1.0

        _append_unique(
            positive_evidence,
            (
                f"Visual model has strong confidence "
                f"({confidence:.0%})"
            ),
        )

    elif confidence >= 0.75:

        quality = 0.75

        _append_unique(
            positive_evidence,
            (
                f"Visual model has usable confidence "
                f"({confidence:.0%})"
            ),
        )

    elif confidence >= 0.60:

        quality = 0.50

        _append_unique(
            reasons,
            (
                f"Visual model confidence is moderate "
                f"({confidence:.0%})"
            ),
        )

    else:

        quality = 0.25

        _append_unique(
            reasons,
            (
                f"Visual model confidence is weak "
                f"({confidence:.0%})"
            ),
        )

    return {
        "available": True,
        "confidence": round(
            confidence,
            3,
        ),
        "authentic_probability": round(
            authentic,
            3,
        ),
        "forged_probability": round(
            forged,
            3,
        ),
        "quality": round(
            quality,
            3,
        ),
    }


# ============================================================================
# TAMPERING QUALITY
# ============================================================================

def _evaluate_tampering(
    tampering: Dict[str, Any],
    positive_evidence: List[str],
) -> Dict[str, Any]:
    """
    Determine whether tampering analysis was performed.

    Important:
        A low tampering score is not the same thing as high evidence quality.

    This only measures whether the module supplied a usable analysis.
    """

    if not isinstance(
        tampering,
        dict,
    ):

        return {
            "available": False,
            "quality": 0.0,
        }

    if "tampering_score" not in tampering:

        return {
            "available": False,
            "quality": 0.0,
        }

    score = _normalise_probability(
        tampering.get(
            "tampering_score",
            0.0,
        )
    )

    _append_unique(
        positive_evidence,
        "Image tampering analysis was performed",
    )

    return {
        "available": True,
        "tampering_score": round(
            score,
            3,
        ),
        "quality": 1.0,
    }


# ============================================================================
# FACE QUALITY
# ============================================================================

def _evaluate_face(
    face: Dict[str, Any],
    positive_evidence: List[str],
    reasons: List[str],
) -> Dict[str, Any]:
    """
    Evaluate face-verification availability.

    Missing live photo is NOT proof of forgery.

    It reduces evidence completeness.
    """

    if not isinstance(
        face,
        dict,
    ):

        face = {}

    performed = bool(
        face.get(
            "performed",
            False,
        )
    )

    if not performed:

        _append_unique(
            reasons,
            "Face verification was not performed",
        )

        return {
            "performed": False,
            "quality": 0.0,
        }

    similarity = _normalise_probability(
        face.get(
            "similarity",
            0.0,
        )
    )

    _append_unique(
        positive_evidence,
        "Live face verification was performed",
    )

    return {
        "performed": True,
        "similarity": round(
            similarity,
            3,
        ),
        "quality": 1.0,
    }


# ============================================================================
# CRITICAL FIELD QUALITY
# ============================================================================

def _evaluate_critical_fields(
    ocr_result: Dict[str, Any],
    document_type: str,
    reasons: List[str],
    positive_evidence: List[str],
) -> Dict[str, Any]:
    """
    Evaluate whether critical identity fields were successfully extracted.
    """

    # ------------------------------------------------------------------------
    # Select critical fields.
    # ------------------------------------------------------------------------

    critical_fields = set(
        GENERAL_CRITICAL_FIELDS
    )

    if document_type == "passport":

        critical_fields.update(
            {
                "surname",
                "given_names",
                "date_of_expiry",
            }
        )

    elif document_type == "driving_license":

        critical_fields.update(
            {
                "surname",
                "given_names",
            }
        )

    elif document_type == "national_id":

        critical_fields.update(
            {
                "surname",
                "given_names",
            }
        )

    elif document_type == "visa":

        critical_fields.update(
            {
                "visa_number",
                "date_of_expiry",
            }
        )

    # ------------------------------------------------------------------------
    # Unknown type.
    # ------------------------------------------------------------------------

    if document_type == "unknown":

        # We can still look for general identity fields.
        critical_fields = GENERAL_CRITICAL_FIELDS

    # ------------------------------------------------------------------------
    # Count reliable fields.
    # ------------------------------------------------------------------------

    extracted = []

    missing = []

    for field_name in sorted(
        critical_fields
    ):

        if _field_is_reliable(
            ocr_result,
            field_name,
        ):

            extracted.append(
                field_name
            )

        else:

            missing.append(
                field_name
            )

    total = len(
        critical_fields
    )

    if total:

        ratio = (
            len(extracted)
            / total
        )

    else:

        ratio = 0.0

    # ------------------------------------------------------------------------
    # Reasons.
    # ------------------------------------------------------------------------

    if len(extracted) == 0:

        _append_unique(
            reasons,
            "No critical identity fields were reliably extracted",
        )

    elif ratio < 0.50:

        _append_unique(
            reasons,
            (
                f"Only {len(extracted)} of {total} critical "
                "identity fields were reliably extracted"
            ),
        )

    else:

        _append_unique(
            positive_evidence,
            (
                f"{len(extracted)} critical identity field(s) "
                "were reliably extracted"
            ),
        )

    return {
        "critical_fields": sorted(
            critical_fields
        ),
        "extracted_fields": extracted,
        "missing_fields": missing,
        "ratio": round(
            ratio,
            3,
        ),
    }


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def assess_evidence_quality(
    ocr_result: Dict[str, Any],
    validation: Dict[str, Any],
    forgery: Dict[str, Any],
    tampering: Dict[str, Any],
    face: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Main ARGUS evidence-quality function.

    Returns a structured evidence assessment.

    The returned `quality_score` is in [0, 1].

    `sufficient_for_decision` is True ONLY when:

        quality_score >= MIN_DECISION_EVIDENCE

    and there is no explicit evidence-quality failure.

    This function does NOT make an authenticity/forgery decision.
    """

    # =========================================================================
    # NORMALIZE INPUTS
    # =========================================================================

    if not isinstance(
        ocr_result,
        dict,
    ):

        ocr_result = {}

    if not isinstance(
        validation,
        dict,
    ):

        validation = {}

    if not isinstance(
        forgery,
        dict,
    ):

        forgery = {}

    if not isinstance(
        tampering,
        dict,
    ):

        tampering = {}

    if not isinstance(
        face,
        dict,
    ):

        face = {}

    reasons: List[str] = []

    positive_evidence: List[str] = []

    # =========================================================================
    # 1. DOCUMENT TYPE
    # =========================================================================

    document_type_result = _evaluate_document_type(
        ocr_result,
        reasons,
        positive_evidence,
    )

    document_type = document_type_result[
        "document_type"
    ]

    document_type_confidence = document_type_result[
        "confidence"
    ]

    document_type_quality = document_type_result[
        "quality"
    ]

    # =========================================================================
    # 2. OCR
    # =========================================================================

    ocr_quality = _evaluate_ocr_quality(
        ocr_result,
        document_type,
        reasons,
        positive_evidence,
    )

    # =========================================================================
    # 3. MRZ
    # =========================================================================

    mrz_quality = _evaluate_mrz(
        ocr_result,
        reasons,
        positive_evidence,
    )

    # =========================================================================
    # 4. VALIDATION
    # =========================================================================

    validation_quality = _evaluate_validation(
        validation,
        reasons,
        positive_evidence,
    )

    # =========================================================================
    # 5. VISUAL MODEL
    # =========================================================================

    visual_quality = _evaluate_visual_model(
        forgery,
        reasons,
        positive_evidence,
    )

    # =========================================================================
    # 6. TAMPERING
    # =========================================================================

    tampering_quality = _evaluate_tampering(
        tampering,
        positive_evidence,
    )

    # =========================================================================
    # 7. FACE
    # =========================================================================

    face_quality = _evaluate_face(
        face,
        positive_evidence,
        reasons,
    )

    # =========================================================================
    # 8. CRITICAL FIELDS
    # =========================================================================

    critical_fields = _evaluate_critical_fields(
        ocr_result,
        document_type,
        reasons,
        positive_evidence,
    )

    # =========================================================================
    # 9. CALCULATE EVIDENCE SCORE
    # =========================================================================
    #
    # Evidence quality is intentionally NOT simply an average.
    #
    # Document identity and reliable extraction matter more than auxiliary
    # signals.
    #
    # Base components:
    #
    #   Document type          20%
    #   OCR quality            20%
    #   Critical fields        20%
    #   MRZ / validation       15%
    #   Visual model           15%
    #   Tampering analysis      5%
    #   Face verification       5%
    #
    # Total = 100%
    #
    # However, face and tampering are allowed to be absent without causing
    # catastrophic evidence failure because they are optional modules.
    #

    # Combine MRZ and validation.
    document_validation_quality = max(
        mrz_quality["quality"],
        validation_quality["quality"],
    )

    # Base score.
    base_score = (
        (document_type_quality * 0.20)
        + (ocr_quality["quality"] * 0.20)
        + (critical_fields["ratio"] * 0.20)
        + (document_validation_quality * 0.15)
        + (visual_quality["quality"] * 0.15)
        + (tampering_quality["quality"] * 0.05)
        + (face_quality["quality"] * 0.05)
    )

    # =========================================================================
    # 10. OPTIONAL-MODULE NORMALIZATION
    # =========================================================================
    #
    # Face verification and tampering analysis may legitimately be absent
    # during document-only screening.
    #
    # Therefore, don't permanently lose 10 percentage points merely because
    # those optional modules weren't supplied.
    #
    # Instead redistribute their weights among available evidence sources.
    #

    components = [
        (
            document_type_quality,
            0.20,
            True,
        ),
        (
            ocr_quality["quality"],
            0.20,
            True,
        ),
        (
            critical_fields["ratio"],
            0.20,
            True,
        ),
        (
            document_validation_quality,
            0.15,
            True,
        ),
        (
            visual_quality["quality"],
            0.15,
            visual_quality["available"],
        ),
        (
            tampering_quality["quality"],
            0.05,
            tampering_quality["available"],
        ),
        (
            face_quality["quality"],
            0.05,
            face_quality["performed"],
        ),
    ]

    available_weight = sum(
        weight
        for _, weight, available
        in components
        if available
    )

    if available_weight > 0:

        normalized_score = sum(
            value * weight
            for value, weight, available
            in components
            if available
        ) / available_weight

    else:

        normalized_score = 0.0

    # =========================================================================
    # 11. CONSERVATIVE HARD CAPS
    # =========================================================================
    #
    # Some situations should prevent the evidence score from becoming high
    # simply because the visual model is confident.
    #
    # This is critical for your current problem.
    #
    # Example:
    #
    #   document type = unknown
    #   critical fields = poor
    #   visual model = 96% authentic
    #
    # This MUST NOT become 0.90+ evidence quality.
    #

    # -------------------------------------------------------------------------
    # Unknown document type
    # -------------------------------------------------------------------------

    if (
        document_type == "unknown"
        or document_type_confidence < MIN_DOCUMENT_TYPE_CONFIDENCE
    ):

        normalized_score = min(
            normalized_score,
            0.70,
        )

    # -------------------------------------------------------------------------
    # Very poor critical-field extraction
    # -------------------------------------------------------------------------

    if critical_fields["ratio"] < 0.40:

        normalized_score = min(
            normalized_score,
            0.70,
        )

    # -------------------------------------------------------------------------
    # No usable OCR
    # -------------------------------------------------------------------------

    if ocr_quality["quality"] < 0.30:

        normalized_score = min(
            normalized_score,
            0.60,
        )

    # -------------------------------------------------------------------------
    # No document validation evidence
    # -------------------------------------------------------------------------

    if (
        document_validation_quality <= 0.0
        and document_type == "unknown"
    ):

        normalized_score = min(
            normalized_score,
            0.60,
        )

    # -------------------------------------------------------------------------
    # Clamp final score.
    # -------------------------------------------------------------------------

    quality_score = round(
        _clamp(
            normalized_score
        ),
        3,
    )

    # =========================================================================
    # 12. QUALITY LABEL
    # =========================================================================

    if quality_score >= MIN_DECISION_EVIDENCE:

        quality_label = "HIGH"

        tier = "HIGH"

    elif quality_score >= MIN_MEDIUM_EVIDENCE:

        quality_label = "MEDIUM"

        tier = "MEDIUM"

    else:

        quality_label = "LOW"

        tier = "LOW"

    # =========================================================================
    # 13. FINAL SUFFICIENCY
    # =========================================================================
    #
    # The score is the hard lower bound.
    #
    # But several structural failures also veto a confident decision.
    #

    sufficient_for_decision = (
        quality_score >= MIN_DECISION_EVIDENCE
    )

    # Unknown document type cannot produce a confident final identity
    # authenticity decision in the current architecture.
    if document_type == "unknown":

        sufficient_for_decision = False

    # Weak document type identification also vetoes a confident decision.
    if document_type_confidence < MIN_DOCUMENT_TYPE_CONFIDENCE:

        sufficient_for_decision = False

    # No reliable critical identity fields veto the decision.
    if critical_fields["ratio"] < 0.50:

        sufficient_for_decision = False

    # =========================================================================
    # 14. ADD FINAL EXPLANATIONS
    # =========================================================================

    if sufficient_for_decision:

        _append_unique(
            positive_evidence,
            (
                "Evidence quality meets the minimum threshold "
                f"for a confident decision ({quality_score:.0%})"
            ),
        )

    else:

        if quality_score < MIN_MEDIUM_EVIDENCE:

            _append_unique(
                reasons,
                (
                    "Evidence quality is too low for a confident "
                    "authenticity decision"
                ),
            )

        else:

            _append_unique(
                reasons,
                (
                    "Evidence quality is insufficient for a confident "
                    "authenticity decision"
                ),
            )

        if document_type == "unknown":

            _append_unique(
                reasons,
                "Document type must be identified before a confident decision",
            )

        if critical_fields["ratio"] < 0.50:

            _append_unique(
                reasons,
                "Critical identity fields are insufficiently reliable",
            )

    # =========================================================================
    # 15. RETURN
    # =========================================================================

    return {

        # ---------------------------------------------------------------------
        # Primary score
        # ---------------------------------------------------------------------

        "score": quality_score,

        "quality_score": quality_score,

        "tier": tier,

        "quality_label": quality_label,

        "confidence": quality_score,

        "sufficient_for_decision": sufficient_for_decision,

        # ---------------------------------------------------------------------
        # Document type
        # ---------------------------------------------------------------------

        "document_type": document_type,

        "document_type_confidence": round(
            document_type_confidence,
            3,
        ),

        # ---------------------------------------------------------------------
        # Detailed components
        # ---------------------------------------------------------------------

        "components": {

            "document_type": {
                "quality": round(
                    document_type_quality,
                    3,
                ),
                "confidence": round(
                    document_type_confidence,
                    3,
                ),
            },

            "ocr": ocr_quality,

            "critical_fields": critical_fields,

            "mrz": mrz_quality,

            "validation": validation_quality,

            "visual_model": visual_quality,

            "tampering": tampering_quality,

            "face": face_quality,
        },

        # ---------------------------------------------------------------------
        # Human-readable evidence
        # ---------------------------------------------------------------------

        "reasons": reasons,

        "positive_evidence": positive_evidence,
    }


# ============================================================================
# BACKWARD-COMPATIBILITY ALIAS
# ============================================================================

def assess_evidence(
    ocr_result: Dict[str, Any],
    validation: Dict[str, Any],
    forgery: Dict[str, Any],
    tampering: Dict[str, Any],
    face: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Backward-compatible alias.

    Allows older ARGUS pipeline code to continue calling:

        assess_evidence(...)

    while the canonical function is:

        assess_evidence_quality(...)
    """

    return assess_evidence_quality(
        ocr_result=ocr_result,
        validation=validation,
        forgery=forgery,
        tampering=tampering,
        face=face,
    )
# Evidence Quality Scorer: Weights sharpness, illumination balance, and noise profile.

"""
ARGUS Risk Engine
=================

Combines:

    - Document validation
    - Rule-based forgery analysis
    - Visual forgery prediction
    - Tampering analysis
    - Face verification
    - Evidence quality

IMPORTANT
---------
Evidence quality is a HARD DECISION GATE.

A low-quality / insufficient-evidence case MUST NOT receive a confident
AUTHENTIC or SUSPICIOUS/FORGED decision merely because a model has a high
probability.

Example:

    Visual model:       96% authentic
    Evidence quality:   70%
    Document type:      unknown
    Field extraction:   poor

    -> FINAL DECISION: INCONCLUSIVE

The numerical risk score is still calculated for diagnostics.

The numerical risk score answers:

    "How suspicious are the available signals?"

The final decision answers:

    "Do we have enough reliable evidence to make a decision?"

These are intentionally separate concepts.

This module is document-type agnostic. It does not contain special cases
for passports, Aadhaar, driving licences, visas, etc. Document-specific
evidence quality is handled upstream by evidence_quality.py.
"""

from typing import Dict, Any


# ============================================================================
# THRESHOLDS
# ============================================================================

# Numerical risk thresholds.
LOW_RISK_THRESHOLD = 20.0
MEDIUM_RISK_THRESHOLD = 50.0
HIGH_RISK_THRESHOLD = 75.0


# Evidence-quality thresholds.
#
# >= 0.75:
#     Evidence is sufficient for a confident decision.
#
# >= 0.50 and < 0.75:
#     Evidence is usable but insufficient for a confident decision.
#
# < 0.50:
#     Evidence is poor.
#
MIN_DECISION_EVIDENCE = 0.75
MIN_MEDIUM_EVIDENCE = 0.50


# Model disagreement threshold.
MODEL_DISAGREEMENT_THRESHOLD = 0.25


# ============================================================================
# HELPERS
# ============================================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """
    Safely convert a value to float.

    Invalid / missing values return the supplied default.
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
    Clamp a numeric value to a specified range.
    """

    return max(
        minimum,
        min(maximum, value),
    )


def _get_visual_model(
    forgery: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract visual-model output from ARGUS's forgery structure.

    Expected structure:

        forgery = {
            "rules": {...},
            "visual_model": {
                "authentic_probability": ...,
                "forged_probability": ...
            }
        }

    Also accepts a direct visual-model dictionary for compatibility.
    """

    if not isinstance(forgery, dict):
        return {}

    visual_model = forgery.get("visual_model")

    if isinstance(visual_model, dict):
        return visual_model

    # Backward compatibility with direct model output.
    if (
        "authentic_probability" in forgery
        or "forged_probability" in forgery
    ):
        return forgery

    return {}


def _get_evidence_score(
    evidence_quality: Dict[str, Any],
) -> float:
    """
    Extract and normalize the evidence-quality score.

    Supports:

        quality_score

    and the compatibility field:

        score

    The returned value is always in [0, 1].
    """

    if not isinstance(evidence_quality, dict):
        return 0.0

    value = evidence_quality.get("quality_score")

    if value is None:
        value = evidence_quality.get("score")

    return _clamp(
        _safe_float(
            value,
            0.0,
        )
    )


def _get_evidence_sufficiency(
    evidence_quality: Dict[str, Any],
    evidence_score: float,
) -> bool:
    """
    Determine whether evidence is sufficient for a confident decision.

    IMPORTANT
    ---------
    The risk engine is the FINAL decision authority.

    The numerical evidence threshold is a hard lower bound.

    Therefore:

        evidence_score < MIN_DECISION_EVIDENCE
            -> always insufficient

    Even if evidence_quality.py incorrectly reports:

        sufficient_for_decision = True

    the risk engine will still reject the evidence.

    Conversely, evidence_quality.py is allowed to veto a decision:

        sufficient_for_decision = False
            -> insufficient

    This produces a conservative one-way gate:

        Evidence module can say NO.
        Risk engine independently verifies the minimum score.
        Neither can bypass the hard threshold.
    """

    if not isinstance(evidence_quality, dict):
        return False

    # ------------------------------------------------------------------------
    # HARD NUMERICAL GATE
    # ------------------------------------------------------------------------
    #
    # This must always be checked first.
    #
    if evidence_score < MIN_DECISION_EVIDENCE:
        return False

    # ------------------------------------------------------------------------
    # EXPLICIT QUALITY-MODULE VETO
    # ------------------------------------------------------------------------

    explicit = evidence_quality.get(
        "sufficient_for_decision"
    )

    if explicit is False:
        return False

    # ------------------------------------------------------------------------
    # OTHERWISE SUFFICIENT
    # ------------------------------------------------------------------------

    return True


def _append_unique(
    reasons: list,
    message: str,
) -> None:
    """
    Append a reason only if it is not already present.
    """

    if not message:
        return

    message = str(message)

    if message not in reasons:
        reasons.append(message)


# ============================================================================
# MAIN RISK ENGINE
# ============================================================================

def compute_risk_score(
    validation: Dict[str, Any],
    forgery: Dict[str, Any],
    tampering: Dict[str, Any],
    face: Dict[str, Any],
    evidence_quality: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute ARGUS's final risk assessment.

    Parameters
    ----------
    validation:
        Output from document_validation.py.

    forgery:
        Output from forgery_prediction.py containing:

            - rules
            - visual_model

    tampering:
        Output from tampering_detection.py.

    face:
        Output from face_verification.py.

    evidence_quality:
        Output from evidence_quality.py.

    Returns
    -------
    Dict[str, Any]
        Structured ARGUS risk assessment.

    Decision behaviour
    ------------------
    If evidence is insufficient:

        tier     = "INCONCLUSIVE"
        decision = "INCONCLUSIVE"

    regardless of the numerical risk score or visual-model confidence.

    If evidence is sufficient:

        LOW       -> LIKELY_AUTHENTIC
        MEDIUM    -> SUSPICIOUS
        HIGH      -> LIKELY_FORGED
    """

    # =========================================================================
    # NORMALIZE INPUTS
    # =========================================================================

    validation = (
        validation
        if isinstance(validation, dict)
        else {}
    )

    forgery = (
        forgery
        if isinstance(forgery, dict)
        else {}
    )

    tampering = (
        tampering
        if isinstance(tampering, dict)
        else {}
    )

    face = (
        face
        if isinstance(face, dict)
        else {}
    )

    evidence_quality = (
        evidence_quality
        if isinstance(evidence_quality, dict)
        else {}
    )

    # =========================================================================
    # 1. EVIDENCE QUALITY
    # =========================================================================

    evidence_score = _get_evidence_score(
        evidence_quality
    )

    evidence_sufficient = _get_evidence_sufficiency(
        evidence_quality,
        evidence_score,
    )

    evidence_label = (
        evidence_quality.get("quality_label")
        or evidence_quality.get("tier")
        or "UNKNOWN"
    )

    # =========================================================================
    # 2. VALIDATION RISK
    # =========================================================================

    validation_ratio = _safe_float(
        validation.get("validity_ratio"),
        0.0,
    )

    validation_ratio = _clamp(
        validation_ratio
    )

    validation_risk = 1.0 - validation_ratio

    # Explicit expiration.
    #
    # Expiration is a validity issue, NOT automatic proof of forgery.
    is_expired = (
        validation.get("is_expired") is True
    )

    # =========================================================================
    # 3. RULE-BASED FORGERY RISK
    # =========================================================================

    rules = forgery.get(
        "rules",
        {},
    )

    if not isinstance(rules, dict):
        rules = {}

    rule_score = _safe_float(
        rules.get("forgery_risk_score"),
        0.0,
    )

    # ARGUS rule score is 0-100.
    rule_risk = _clamp(
        rule_score / 100.0
    )

    # =========================================================================
    # 4. VISUAL MODEL RISK
    # =========================================================================

    visual_model = _get_visual_model(
        forgery
    )

    authentic_probability = _safe_float(
        visual_model.get(
            "authentic_probability"
        ),
        0.0,
    )

    forged_probability = _safe_float(
        visual_model.get(
            "forged_probability"
        ),
        0.0,
    )

    authentic_probability = _clamp(
        authentic_probability
    )

    forged_probability = _clamp(
        forged_probability
    )

    # Forged probability is the direct visual risk.
    visual_risk = forged_probability

    # =========================================================================
    # 5. MODEL DISAGREEMENT
    # =========================================================================

    model_disagreement = abs(
        rule_risk - visual_risk
    )

    model_disagreement = _clamp(
        model_disagreement
    )

    # =========================================================================
    # 6. TAMPERING RISK
    # =========================================================================

    tampering_risk = _clamp(
        _safe_float(
            tampering.get(
                "tampering_score"
            ),
            0.0,
        )
    )

    # =========================================================================
    # 7. FACE VERIFICATION RISK
    # =========================================================================

    face_performed = bool(
        face.get(
            "performed",
            False,
        )
    )

    face_risk = 0.0

    if face_performed:

        match = face.get(
            "match"
        )

        similarity = face.get(
            "similarity"
        )

        # Explicit mismatch.
        if match is False:

            face_risk = 1.0

        # Otherwise use similarity when available.
        elif similarity is not None:

            similarity = _clamp(
                _safe_float(
                    similarity,
                    0.0,
                )
            )

            face_risk = 1.0 - similarity

    # IMPORTANT:
    #
    # If face verification wasn't performed, we do NOT automatically
    # increase forgery risk.
    #
    # Missing live verification is an evidence limitation, not proof
    # of forgery.
    #

    # =========================================================================
    # 8. COMBINED NUMERICAL RISK
    # =========================================================================
    #
    # This score is ALWAYS calculated.
    #
    # It remains useful for:
    #
    #   - diagnostics
    #   - analytics
    #   - debugging
    #   - ranking suspicious cases
    #   - future calibration
    #
    # It does NOT override the evidence-quality gate.
    #
    # Weights:
    #
    #   rule-based evidence       35%
    #   visual model              30%
    #   tampering                 15%
    #   validation                10%
    #   model disagreement         5%
    #   face                        5%
    #
    # Total = 100%
    #

    raw_risk = (
        (rule_risk * 0.35)
        + (visual_risk * 0.30)
        + (tampering_risk * 0.15)
        + (validation_risk * 0.10)
        + (model_disagreement * 0.05)
        + (face_risk * 0.05)
    )

    raw_risk = _clamp(
        raw_risk
    )

    risk_score = round(
        raw_risk * 100.0,
        1,
    )

    # =========================================================================
    # 9. COLLECT REASONS
    # =========================================================================

    reasons = []

    # -------------------------------------------------------------------------
    # Validation issues
    # -------------------------------------------------------------------------

    validation_issues = validation.get(
        "issues",
        [],
    )

    if isinstance(
        validation_issues,
        list,
    ):

        for issue in validation_issues:

            if issue:
                _append_unique(
                    reasons,
                    str(issue),
                )

    # -------------------------------------------------------------------------
    # Rule-based forgery reasons
    # -------------------------------------------------------------------------

    rule_reasons = rules.get(
        "reasons",
        [],
    )

    if isinstance(
        rule_reasons,
        list,
    ):

        for reason in rule_reasons:

            if reason:
                _append_unique(
                    reasons,
                    str(reason),
                )

    # -------------------------------------------------------------------------
    # Expiration
    # -------------------------------------------------------------------------

    if is_expired:

        _append_unique(
            reasons,
            "Document is expired",
        )

    # -------------------------------------------------------------------------
    # Tampering
    # -------------------------------------------------------------------------

    if tampering_risk >= 0.70:

        _append_unique(
            reasons,
            (
                "Strong tampering evidence detected "
                f"({tampering_risk:.0%})"
            ),
        )

    elif tampering_risk >= 0.40:

        _append_unique(
            reasons,
            (
                "Moderate tampering evidence detected "
                f"({tampering_risk:.0%})"
            ),
        )

    # -------------------------------------------------------------------------
    # Face verification
    # -------------------------------------------------------------------------

    if face_performed:

        if face.get("match") is False:

            _append_unique(
                reasons,
                (
                    "Live face does not sufficiently match "
                    "the document portrait"
                ),
            )

    else:

        _append_unique(
            reasons,
            "Face verification skipped: No live photo provided",
        )

    # -------------------------------------------------------------------------
    # Model disagreement
    # -------------------------------------------------------------------------

    if model_disagreement >= MODEL_DISAGREEMENT_THRESHOLD:

        _append_unique(
            reasons,
            (
                "Rule-based and visual forgery models show "
                f"meaningful disagreement ({model_disagreement:.0%})"
            ),
        )

    # =========================================================================
    # 10. EVIDENCE QUALITY GATE
    # =========================================================================
    #
    # THIS IS THE PRIMARY DECISION GATE.
    #
    # Example:
    #
    #     Visual model = 96% authentic
    #     Evidence     = 70%
    #     Type         = unknown
    #
    # Result:
    #
    #     score    = whatever the numerical calculation produces
    #     tier     = INCONCLUSIVE
    #     decision = INCONCLUSIVE
    #
    # The numerical score does NOT become "LOW" simply because it is below
    # LOW_RISK_THRESHOLD.
    #

    if not evidence_sufficient:

        tier = "INCONCLUSIVE"

        decision = "INCONCLUSIVE"

        if evidence_score < MIN_MEDIUM_EVIDENCE:

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

    # =========================================================================
    # 11. NORMAL DECISION PATH
    # =========================================================================

    else:

        # ---------------------------------------------------------------------
        # High risk
        # ---------------------------------------------------------------------

        if risk_score >= HIGH_RISK_THRESHOLD:

            tier = "HIGH"

            decision = "LIKELY_FORGED"

        # ---------------------------------------------------------------------
        # Medium risk
        # ---------------------------------------------------------------------

        elif risk_score >= MEDIUM_RISK_THRESHOLD:

            tier = "MEDIUM"

            decision = "SUSPICIOUS"

        # ---------------------------------------------------------------------
        # Low risk
        # ---------------------------------------------------------------------

        else:

            tier = "LOW"

            decision = "LIKELY_AUTHENTIC"

    # =========================================================================
    # 12. DIRECT FORGERY OVERRIDE
    # =========================================================================
    #
    # Extremely strong independent forgery evidence can remain actionable
    # even if general evidence quality is imperfect.
    #
    # This is intentionally conservative.
    #
    # We require:
    #
    #     at least TWO strong independent rule signals
    #
    # AND:
    #
    #     rule risk >= 0.75
    #
    # This prevents a single weak OCR error from declaring a document forged.
    #
    # Expiration alone is NEVER considered proof of forgery.
    #

    direct_forgery_signal = False

    triggered_signals = rules.get(
        "triggered_signals",
        {},
    )

    if isinstance(
        triggered_signals,
        dict,
    ):

        strong_signals = 0

        # Invalid structural format.
        if triggered_signals.get(
            "format_invalid"
        ) is True:

            strong_signals += 1

        # Failed MRZ checksum.
        if triggered_signals.get(
            "mrz_checksum_failed"
        ) is True:

            strong_signals += 1

        # Impossible date.
        if triggered_signals.get(
            "impossible_date"
        ) is True:

            strong_signals += 1

        # Known forgery pattern.
        if triggered_signals.get(
            "known_forgery_pattern"
        ) is True:

            strong_signals += 1

        if strong_signals >= 2:

            direct_forgery_signal = True

    # -------------------------------------------------------------------------
    # Apply conservative direct-forgery override.
    # -------------------------------------------------------------------------

    if (
        not evidence_sufficient
        and direct_forgery_signal
        and rule_risk >= 0.75
    ):

        tier = "HIGH"

        decision = "LIKELY_FORGED"

        _append_unique(
            reasons,
            (
                "Strong independent forgery signals remain actionable "
                "despite limited evidence quality"
            ),
        )

    # =========================================================================
    # 13. FACE MISMATCH OVERRIDE
    # =========================================================================
    #
    # A face mismatch can strengthen an already sufficiently evidenced case.
    #
    # It does NOT override insufficient document evidence.
    #

    if (
        face_performed
        and face.get("match") is False
        and face_risk >= 0.80
    ):

        if evidence_sufficient:

            tier = "HIGH"

            decision = "SUSPICIOUS"

            _append_unique(
                reasons,
                "Strong face-verification mismatch detected",
            )

    # =========================================================================
    # 14. EVIDENCE SUMMARY
    # =========================================================================

    evidence_reasons = evidence_quality.get(
        "reasons",
        [],
    )

    if not isinstance(
        evidence_reasons,
        list,
    ):
        evidence_reasons = []

    positive_evidence = evidence_quality.get(
        "positive_evidence",
        [],
    )

    if not isinstance(
        positive_evidence,
        list,
    ):
        positive_evidence = []

    # =========================================================================
    # 15. RETURN RESULT
    # =========================================================================

    return {

        # ---------------------------------------------------------------------
        # Numerical risk score
        # ---------------------------------------------------------------------

        "score": risk_score,

        # ---------------------------------------------------------------------
        # Final classification tier
        # ---------------------------------------------------------------------

        "tier": tier,

        # ---------------------------------------------------------------------
        # Final decision
        # ---------------------------------------------------------------------

        "decision": decision,

        # ---------------------------------------------------------------------
        # Decision confidence
        #
        # This is intentionally based on evidence quality rather than the
        # visual model's probability.
        #
        # Example:
        #
        #     visual authenticity = 0.96
        #     evidence quality    = 0.70
        #
        #     decision             = INCONCLUSIVE
        #     decision_confidence  = 0.70
        #
        # ---------------------------------------------------------------------

        "decision_confidence": round(
            evidence_score,
            3,
        ),

        # ---------------------------------------------------------------------
        # Numerical risk breakdown
        # ---------------------------------------------------------------------

        "breakdown": {

            "forgery_risk": round(
                rule_risk,
                3,
            ),

            "rule_risk": round(
                rule_risk,
                3,
            ),

            "visual_risk": round(
                visual_risk,
                3,
            ),

            "tampering_risk": round(
                tampering_risk,
                3,
            ),

            "face_risk": round(
                face_risk,
                3,
            ),

            "model_disagreement": round(
                model_disagreement,
                3,
            ),

            "validation_risk": round(
                validation_risk,
                3,
            ),

            "evidence_quality": round(
                evidence_score,
                3,
            ),
        },

        # ---------------------------------------------------------------------
        # Evidence-quality information
        # ---------------------------------------------------------------------

        "evidence_quality": {

            "score": round(
                evidence_score,
                3,
            ),

            "label": evidence_label,

            "sufficient_for_decision": evidence_sufficient,

            "reasons": evidence_reasons,

            "positive_evidence": positive_evidence,
        },

        # ---------------------------------------------------------------------
        # Human-readable reasons
        # ---------------------------------------------------------------------

        "reasons": reasons,
    }
# Risk Engine Policy: Deterministic APH violations trigger immediate non-compliant flags.

# Decoupled Architecture: Mathematical solvers evaluate statutory APH rules independently.

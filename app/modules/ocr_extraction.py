"""
Module 1: OCR Extraction

Two extraction paths:
1. MRZ (Machine Readable Zone) parsing for passports/IDs that have one.
   This is the strongest signal we have: the MRZ encodes check digits for
   the document number, date of birth, expiry date, and a composite
   checksum. If these don't validate, that's a real (not simulated)
   tampering/error signal, computed in Module 2.
2. Label/value proximity extraction (EasyOCR with bounding boxes) for
   documents with no MRZ - visas, driving licences, permits. Most of
   these print a field label ("Visa No.", "Date of Expiry", "Class") next
   to or above its value, so once we have box positions we can pair them
   up directly instead of guessing from a flat text blob.
"""

import re
import cv2
import numpy as np
from datetime import date
from typing import Optional
from mrz.checker.td3 import TD3CodeChecker
from mrz.checker.td1 import TD1CodeChecker

try:
    from dateutil import parser as _dateparser
except ImportError:  # pragma: no cover - dateutil is in requirements.txt
    _dateparser = None

_reader = None  # lazy-loaded, EasyOCR init is slow


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["en"], gpu=False)
    return _reader


# --------------------------------------------------------------------------
# MRZ path (passports, and IDs that carry a TD1/TD3 MRZ)
# --------------------------------------------------------------------------

def _find_mrz_lines(boxes: list[dict]) -> list[dict]:
    """MRZ lines are long, mostly uppercase, and heavy with '<' fill
    characters. Returns the matching boxes (text + OCR confidence), not
    just text - the confidence is surfaced in the final result so a
    checksum failure can be read alongside "was this line read cleanly?"
    context instead of as an unqualified pass/fail."""
    candidates = []
    for b in boxes:
        text = b["text"].replace(" ", "").upper()
        if len(text) >= 30 and text.count("<") >= 3:
            candidates.append({"text": text, "conf": b["conf"]})
    return candidates


def _strip_isolated_filler_noise(line: str) -> str:
    """Fix a specific, real OCR failure mode seen on a photographed passport:
    a single spurious letter hallucinated deep inside a long run of '<'
    filler characters (guilloche/security-pattern print bleeding through).
    Conservative on purpose: only strips a letter that sits between filler
    on both immediate sides AND has a run of 3+ '<' before it - that rules
    out a genuine single-letter name component (e.g. a middle initial),
    which would sit right after real name content, not deep in a filler run.
    """
    chars = list(line)
    n = len(chars)
    for i in range(n):
        if not chars[i].isalpha():
            continue
        left_is_filler = i > 0 and chars[i - 1] == "<"
        right_is_filler = i < n - 1 and chars[i + 1] == "<"
        if not (left_is_filler and right_is_filler):
            continue
        left_run = 0
        j = i - 1
        while j >= 0 and chars[j] == "<":
            left_run += 1
            j -= 1
        if left_run >= 3:
            chars[i] = "<"
    return "".join(chars)


# --------------------------------------------------------------------------
# MRZ OCR confusable-character correction
# --------------------------------------------------------------------------
# ICAO 9303 defines exactly which MRZ positions must be alphabetic, which
# must be numeric, and which are free alphanumeric. EasyOCR doesn't know
# this and regularly confuses O<->0, I<->1, S<->5, Z<->2, B<->8 - we saw
# both directions of this in real testing:
#   - a synthetic passport's nationality "UTO" OCR'd as "UT0" (letter->digit)
#   - a real specimen's nationality "EOL" OCR'd as "E0L" (letter->digit)
#   - the same specimen's document number "PP3000000" OCR'd with stray "O"s
#     in place of zeros (digit->letter) - see note below on why this one
#     field can't be safely auto-corrected.
# Since we know the *expected type* of every position in a TD3/TD1 line,
# we can correct confusions deterministically instead of hoping the OCR
# engine got each one right. Fields that ICAO defines as pure alphanumeric
# (document number, personal number) are deliberately left uncorrected:
# both letters and digits are legitimate there, so there's no safe rule to
# apply - a real "PP3000000" and a real "PP3OOO0OO" are not distinguishable
# from position alone.
_DIGIT_LOOKS_LIKE_ALPHA = {"0": "O", "1": "I", "5": "S", "2": "Z", "8": "B"}
_ALPHA_LOOKS_LIKE_DIGIT = {v: k for k, v in _DIGIT_LOOKS_LIKE_ALPHA.items()}

# Position -> expected type for each fixed MRZ format. 'A' = alphabetic
# (letters or '<' filler only), 'N' = numeric, 'X' = free alphanumeric
# (left uncorrected).
_TD3_LINE1_TYPES = "AA" + "AAA" + "A" * 39          # doc type+suffix, country, name field
_TD3_LINE2_TYPES = "X" * 9 + "N" + "AAA" + "N" * 6 + "N" + "A" + "N" * 6 + "N" + "X" * 14 + "N" + "N"
_TD1_LINE1_TYPES = "AA" + "AAA" + "X" * 9 + "N" + "X" * 15   # doc type+suffix, issuing state, doc number, check digit, optional
_TD1_LINE2_TYPES = "N" * 6 + "N" + "A" + "N" * 6 + "N" + "AAA" + "X" * 11 + "N"
_TD1_LINE3_TYPES = "A" * 30                          # name field


def _normalize_mrz_line_width(line: str, width: int) -> str:
    """OCR very commonly drops or duplicates a trailing '<' filler character
    - harmless to correct, since fillers carry no information. Pad short
    lines with '<'; trim long lines only if the excess is itself filler
    (never guess away what might be real content)."""
    if len(line) == width:
        return line
    if len(line) < width:
        return line.ljust(width, "<")
    excess = line[width:]
    if excess and set(excess) == {"<"}:
        return line[:width]
    return line  # can't safely normalize - let downstream parsing fail cleanly


def _correct_mrz_line(line: str, type_map: str) -> str:
    """Apply the alpha<->digit correction above, position by position."""
    if len(line) != len(type_map):
        return line  # length mismatch - leave alone, downstream parse will fail cleanly
    out = []
    for ch, expected in zip(line, type_map):
        if expected == "A" and ch in _DIGIT_LOOKS_LIKE_ALPHA:
            out.append(_DIGIT_LOOKS_LIKE_ALPHA[ch])
        elif expected == "N" and ch in _ALPHA_LOOKS_LIKE_DIGIT:
            out.append(_ALPHA_LOOKS_LIKE_DIGIT[ch])
        else:
            out.append(ch)
    return "".join(out)


def _correct_td3_mrz(line1: str, line2: str) -> tuple[str, str]:
    return (
        _correct_mrz_line(line1, _TD3_LINE1_TYPES),
        _correct_mrz_line(line2, _TD3_LINE2_TYPES),
    )


def _correct_td1_mrz(line1: str, line2: str, line3: str) -> tuple[str, str, str]:
    return (
        _correct_mrz_line(line1, _TD1_LINE1_TYPES),
        _correct_mrz_line(line2, _TD1_LINE2_TYPES),
        _correct_mrz_line(line3, _TD1_LINE3_TYPES),
    )


def _try_parse_mrz(mrz_lines: list[str], boxes: Optional[list[dict]] = None) -> Optional[dict]:
    """Try TD3 (passport, 2 lines x 44 chars) then TD1 (ID card, 3 lines x 30 chars).

    NOTE on the `mrz` library's real API: the checker objects do NOT expose
    check_document_number() / check_birth_date() / check_expiry_date() /
    check_composite() methods. The actual per-field checksum results are
    boolean *properties*: document_number_hash, birth_date_hash,
    expiry_date_hash, final_hash (the "composite" check). Overall document
    validity - including non-checksum field-format checks like a
    non-alphabetic nationality code - is bool(checker).

    NOTE on `fields().surname` / `.name`: when the library can't parse the
    name portion of the MRZ (e.g. OCR inserted a stray letter into what
    should be '<' filler), it does NOT raise or return None - it returns
    the literal string 'None'. Left unguarded this silently renders as
    "None None" in the UI. We detect that sentinel and fall back to the
    label/value OCR pass (the printed "Surname"/"Given Names" fields most
    passports also carry) if box data is available.
    """
    if len(mrz_lines) >= 2:
        try:
            l1_box, l2_box = mrz_lines[-2], mrz_lines[-1]
            line1_raw = _strip_isolated_filler_noise(_normalize_mrz_line_width(l1_box["text"], 44))
            line2_raw = _strip_isolated_filler_noise(_normalize_mrz_line_width(l2_box["text"], 44))
            line1, line2 = _correct_td3_mrz(line1_raw, line2_raw)
            joined = f"{line1}\n{line2}"
            checker = TD3CodeChecker(joined)
            overall_valid = bool(checker)  # must be evaluated before reading properties
            f = checker.fields()

            surname = None if f.surname == "None" else f.surname
            given_names = None if f.name == "None" else f.name
            name_parse_failed = surname is None or given_names is None

            if name_parse_failed and boxes:
                fallback, _fallback_conf = _extract_labeled_fields(boxes)
                surname = surname or fallback.get("surname")
                given_names = given_names or fallback.get("given_names")

            display_name = " ".join(p for p in (surname, given_names) if p) or None

            result = {
                "mrz_format": "TD3",
                "name": display_name,
                "surname": surname,
                "given_names": given_names,
                "document_number": f.document_number,
                "nationality": f.nationality,
                "date_of_birth": f.birth_date,
                "date_of_expiry": f.expiry_date,
                "sex": f.sex,
                "document_type": f.document_type,
                # OCR confidence of the two MRZ lines actually used - context
                # for interpreting a checksum failure (low confidence makes
                # OCR noise the likelier explanation; high confidence with a
                # failed checksum is a stronger, harder-to-dismiss signal).
                "mrz_ocr_confidence": round((l1_box["conf"] + l2_box["conf"]) / 2, 3),
                "checks": {
                    "document_number_valid": checker.document_number_hash,
                    "birth_date_valid": checker.birth_date_hash,
                    "expiry_date_valid": checker.expiry_date_hash,
                    "composite_valid": checker.final_hash,
                    "overall_valid": overall_valid,
                },
            }
            if name_parse_failed:
                result["warnings"] = ["Name field in MRZ could not be reliably parsed (OCR noise) "
                                       + ("- used printed field as fallback" if display_name else "- no fallback available")]
            return result
        except Exception:
            pass

    if len(mrz_lines) >= 3:
        try:
            l1_box, l2_box, l3_box = mrz_lines[-3], mrz_lines[-2], mrz_lines[-1]
            line1_raw = _strip_isolated_filler_noise(_normalize_mrz_line_width(l1_box["text"], 30))
            line2_raw = _strip_isolated_filler_noise(_normalize_mrz_line_width(l2_box["text"], 30))
            line3_raw = _strip_isolated_filler_noise(_normalize_mrz_line_width(l3_box["text"], 30))
            line1, line2, line3 = _correct_td1_mrz(line1_raw, line2_raw, line3_raw)
            joined = f"{line1}\n{line2}\n{line3}"
            checker = TD1CodeChecker(joined)
            overall_valid = bool(checker)
            f = checker.fields()

            surname = None if f.surname == "None" else f.surname
            given_names = None if f.name == "None" else f.name
            name_parse_failed = surname is None or given_names is None

            if name_parse_failed and boxes:
                fallback, _fallback_conf = _extract_labeled_fields(boxes)
                surname = surname or fallback.get("surname")
                given_names = given_names or fallback.get("given_names")

            display_name = " ".join(p for p in (surname, given_names) if p) or None

            result = {
                "mrz_format": "TD1",
                "name": display_name,
                "surname": surname,
                "given_names": given_names,
                "document_number": f.document_number,
                "nationality": f.nationality,
                "date_of_birth": f.birth_date,
                "date_of_expiry": f.expiry_date,
                "sex": f.sex,
                "document_type": f.document_type,
                "mrz_ocr_confidence": round((l1_box["conf"] + l2_box["conf"] + l3_box["conf"]) / 3, 3),
                "checks": {
                    "document_number_valid": checker.document_number_hash,
                    "birth_date_valid": checker.birth_date_hash,
                    "expiry_date_valid": checker.expiry_date_hash,
                    "composite_valid": checker.final_hash,
                    "overall_valid": overall_valid,
                },
            }
            if name_parse_failed:
                result["warnings"] = ["Name field in MRZ could not be reliably parsed (OCR noise) "
                                       + ("- used printed field as fallback" if display_name else "- no fallback available")]
            return result
        except Exception:
            pass

    return None


# --------------------------------------------------------------------------
# Label/value proximity path (visas, driving licences, permits, plain IDs)
# --------------------------------------------------------------------------

# Canonical field name -> label phrases as they commonly appear on visas,
# national IDs, driving licences and permits. Matched against OCR text
# after lowercasing and stripping punctuation, so "Date of Expiry:",
# "DATE OF EXPIRY", "Date d'expiration" style variants all still hit.
FIELD_LABELS: dict[str, list[str]] = {
    "surname": ["surname", "last name", "family name", "nom"],
    "given_names": ["given name", "given names", "first name", "prenom", "prenoms"],
    "full_name": ["name"],  # only used if surname/given_names weren't found separately
    "document_number": [
        "passport no", "document no", "id no", "identity no",
        "licence no", "license no", "permit no", "card no", "no de passeport",
    ],
    "visa_number": ["visa no", "visa number"],
    "visa_type": ["visa type", "type of visa", "category"],
    "entry_validity": ["entries", "no of entries", "valid for"],
    "duration_of_stay": ["duration of stay", "length of stay"],
    "nationality": ["nationality", "nationalite"],
    "date_of_birth": ["date of birth", "dob", "birth date", "naissance"],
    "date_of_issue": ["date of issue", "issue date", "issued", "date of grant"],
    "date_of_expiry": ["date of expiry", "expiry date", "valid until", "valid till", "expiration"],
    "sex": ["sex", "gender", "sexe"],
    "license_class": ["class", "vehicle class", "cat."],
    "place_of_birth": ["place of birth", "birth place"],
    "issuing_authority": ["authority", "issuing authority", "autorite"],
}

# Fields whose value we also promote to the top level of the result dict
# (mirrors the MRZ branch's shape) so Module 2 (document_validation.py) can
# run expiry / blacklist checks on non-MRZ documents too, not just passports.
_PROMOTE_TO_TOP_LEVEL = {
    "document_number": "document_number",
    "visa_number": "document_number",  # fall back to visa number if no generic doc number
    "date_of_expiry": "date_of_expiry",
    "date_of_birth": "date_of_birth",
    "nationality": "nationality",
    "sex": "sex",
}

DATE_REGEX = re.compile(
    r"\b("
    r"\d{1,2}[\s./-][A-Za-z]{3,9}[\s./-]\d{2,4}"   # 15 JUN 1990 / 15-Jun-1990
    r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"             # 15/06/1990
    r"|\d{4}[/.-]\d{1,2}[/.-]\d{1,2}"               # 1990-06-15
    r")\b"
)

_DOC_NUMBER_REGEX = re.compile(r"\b[A-Z0-9]{6,12}\b")


def _readtext_with_boxes(image) -> list[dict]:
    """EasyOCR with detail=1 to keep bounding boxes - needed for label/value
    pairing. Returns one dict per detected text box."""
    reader = _get_reader()
    raw = reader.readtext(image, detail=1, paragraph=False)
    boxes = []
    for bbox, text, conf in raw:
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        boxes.append({
            "text": text,
            "conf": float(conf),
            "x0": min(xs), "x1": max(xs),
            "y0": min(ys), "y1": max(ys),
            "cx": sum(xs) / 4.0, "cy": sum(ys) / 4.0,
        })
    return boxes


def _normalize_label(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def _match_field_label(norm_text: str) -> Optional[str]:
    """Return the canonical field name if norm_text looks like one of our
    known labels. Longer/more specific phrases are checked first so e.g.
    'date of expiry' matches before a looser partial like 'date'."""
    for field, phrases in sorted(
        FIELD_LABELS.items(), key=lambda kv: -max(len(p) for p in kv[1])
    ):
        for phrase in phrases:
            if phrase in norm_text:
                return field
    return None


def _find_value_box_for_label(label_box: dict, boxes: list[dict]) -> Optional[dict]:
    """
    Heuristic: the value is either the nearest box to the RIGHT on roughly
    the same line ("Label: Value" layout), or - if nothing sits to the
    right - the nearest box directly BELOW ("Label" above "Value", common
    in boxed/form-style layouts). This mirrors how visas, ID cards and
    licences are actually typeset.

    Bilingual documents commonly print two labels before the real value
    ("Passport No.  /  No de passeport   P1234567") - so this doesn't just
    grab the nearest box, it walks candidates in distance order and skips
    any that are themselves recognized labels, only returning the first
    genuine value.

    Returns the whole box (not just its text) so the caller can also read
    the OCR engine's confidence for that value - used for field-level
    confidence scoring. _find_value_for_label() below is the original
    text-only contract, kept intact for existing callers/tests.
    """
    label_h = max(label_box["y1"] - label_box["y0"], 1)
    label_w = max(label_box["x1"] - label_box["x0"], 1)

    def is_label(b: dict) -> bool:
        return _match_field_label(_normalize_label(b["text"])) is not None

    same_line = [
        b for b in boxes
        if b is not label_box
        and b["x0"] > label_box["x1"] - 5
        # Tight vertical tolerance is required: bilingual documents commonly
        # place two rows only ~1.0-1.1x label_h apart (e.g. a "Passport No."
        # row directly above/below a "Country Code" row), so anything above
        # ~0.6x let same-row matching leak into the adjacent row and grab
        # that row's label/value by mistake. Real same-row cy differences
        # were 0-1px in test data; 0.6x leaves comfortable margin without
        # bleeding into neighboring rows.
        and abs(b["cy"] - label_box["cy"]) < label_h * 0.6
    ]
    same_line.sort(key=lambda b: b["x0"])
    for cand in same_line:
        if not is_label(cand):
            return cand

    below = [
        b for b in boxes
        if b is not label_box
        and b["y0"] > label_box["y1"] - 5
        and b["y0"] < label_box["y1"] + label_h * 3
        and abs(b["cx"] - label_box["cx"]) < label_w * 2.5
    ]
    below.sort(key=lambda b: b["y0"])
    for cand in below:
        if not is_label(cand):
            return cand

    return None


def _find_value_for_label(label_box: dict, boxes: list[dict]) -> Optional[str]:
    """Text-only contract, kept exactly as before for backward
    compatibility - see _find_value_box_for_label() for the full box
    (including OCR confidence)."""
    box = _find_value_box_for_label(label_box, boxes)
    return box["text"] if box else None


def _extract_labeled_fields(boxes: list[dict]) -> tuple[dict, dict]:
    """Returns (fields, field_confidence) - field_confidence holds the
    EasyOCR confidence (0-1) of the VALUE box matched to each field, so
    downstream code can tell a cleanly-read field apart from a shaky one
    without re-running OCR or re-deriving positions."""
    fields: dict[str, str] = {}
    field_confidence: dict[str, float] = {}
    for box in boxes:
        norm = _normalize_label(box["text"])
        field = _match_field_label(norm)
        if not field or field in fields:
            continue  # keep the first (usually most confident) match per field
        value_box = _find_value_box_for_label(box, boxes)
        if not value_box:
            continue
        value_text = value_box["text"]
        # guard against pairing a label with what's actually another label
        if _match_field_label(_normalize_label(value_text)) is not None:
            continue
        fields[field] = value_text.strip()
        field_confidence[field] = round(float(value_box["conf"]), 3)
    return fields, field_confidence


def _normalize_date(raw: str) -> Optional[str]:
    """Best-effort parse of a free-form date string into ISO 'YYYY-MM-DD',
    so document_validation.py's _parse_date() can read it directly."""
    if not raw or _dateparser is None:
        return None
    try:
        parsed = _dateparser.parse(raw, dayfirst=True, fuzzy=True)
        if parsed:
            return parsed.date().isoformat()
    except (ValueError, OverflowError):
        pass
    return None


def _guess_fields_from_text(boxes: list[dict]) -> tuple[dict, dict]:
    """
    Best-effort structured extraction for documents without an MRZ (visas,
    national ID cards, driving licences, permits).

    Two passes:
      1. Label/value proximity matching using OCR bounding boxes - the
         reliable path, since most of these documents print field labels.
         Returns per-field confidence alongside the values.
      2. Regex fallback over the full text blob for any dates or
         document-number-looking tokens the label pass missed, or for
         documents with no visible labels at all. No per-field confidence
         here - a regex match over concatenated text from many boxes
         doesn't correspond to any single box's confidence.
    """
    all_text = " ".join(b["text"] for b in boxes)

    fields, field_confidence = _extract_labeled_fields(boxes)

    dates_found = DATE_REGEX.findall(all_text)
    if dates_found:
        fields.setdefault("dates_found", dates_found)

    if not any(k in fields for k in ("document_number", "visa_number")):
        doc_nums = _DOC_NUMBER_REGEX.findall(all_text.upper())
        # drop pure-digit tokens that are really dates already captured above
        doc_nums = [d for d in doc_nums if not d.isdigit()]
        if doc_nums:
            fields["possible_document_numbers"] = doc_nums[:5]

    return fields, field_confidence


def extract_document_fields(image_path: str) -> dict:
    """
    Main entry point for Module 1.
    Returns extracted fields plus MRZ validity checks (if an MRZ was found).

    Always runs the label/value pass on the printed page too, not just when
    there's no MRZ. Reason: passports print human-readable fields alongside
    the MRZ (e.g. full "INDIAN" nationality vs. the MRZ's 3-letter "IND"),
    and some of those printed fields are useful even when the MRZ parsed
    fine. The MRZ stays authoritative at the top level (it's checksummed);
    the printed-page fields live under result["fields"] as a secondary,
    lower-confidence source, and as a fallback if MRZ parsing fails.

    For non-MRZ documents, key fields (document number, expiry date, DOB,
    nationality, sex) are additionally promoted to the top level when
    found, so Module 2 can validate them the same way it validates
    passports.
    """
    image = cv2.imread(image_path)
    if image is None:
        return {"error": "Could not read image", "mrz_found": False, "raw_text": []}

    boxes = _readtext_with_boxes(image)
    ocr_lines = [b["text"] for b in boxes]

    mrz_lines = _find_mrz_lines(boxes)
    mrz_data = _try_parse_mrz(mrz_lines, boxes=boxes) if mrz_lines else None

    result = {
        "mrz_found": mrz_data is not None,
        "raw_text": ocr_lines,
    }

    fields, field_confidence = _guess_fields_from_text(boxes)
    result["fields"] = fields
    result["field_confidence"] = field_confidence

    if mrz_data:
        result.update(mrz_data)
        return result

    # No MRZ (visa, driving licence, permit, plain ID) -> promote label/value
    # fields to the top level so Module 2 can validate them like passports.
    for field_key, top_level_key in _PROMOTE_TO_TOP_LEVEL.items():
        if top_level_key in result:
            continue  # already set by a higher-priority field
        if field_key not in fields:
            continue
        value = fields[field_key]
        if field_key in ("date_of_expiry", "date_of_birth"):
            normalized = _normalize_date(value)
            if normalized:
                result[top_level_key] = normalized
        else:
            result[top_level_key] = value

    return result
# OCR extraction returns structured bounding-boxes with confidence normalization.

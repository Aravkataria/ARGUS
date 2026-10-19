"""
Module 2: Document Validation

Checks extracted fields against:
  - MRZ checksum validity (computed already in Module 1, surfaced here)
  - Expiry date (is the document expired?)
  - A mock blacklist "database" (JSON file) of revoked/flagged document
    numbers, standing in for a real government watchlist lookup.

For a real deployment this module is where you'd plug in an actual
government/INTERPOL document database API instead of the local JSON file.
"""

import json
import os
from datetime import datetime, date
from typing import Optional

BLACKLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "blacklist.json")


def _load_blacklist() -> set[str]:
    if not os.path.exists(BLACKLIST_PATH):
        return set()
    with open(BLACKLIST_PATH) as f:
        data = json.load(f)
    return set(data.get("blacklisted_document_numbers", []))


def _parse_date(value: Optional[str]) -> Optional[date]:
    """MRZ library returns dates as datetime.date already in most versions,
    but handle string forms defensively too."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%y%m%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def validate_document(ocr_result: dict) -> dict:
    issues = []
    checks_passed = 0
    checks_total = 0

    mrz_found = ocr_result.get("mrz_found", False)

    # --- MRZ checksum validity ---
    if mrz_found:
        mrz_checks = ocr_result.get("checks", {})
        for check_name, passed in mrz_checks.items():
            checks_total += 1
            if passed:
                checks_passed += 1
            else:
                issues.append(f"MRZ check failed: {check_name}")
    else:
        issues.append("No MRZ found — falling back to lower-confidence field validation")

    # --- Expiry check ---
    expiry_raw = ocr_result.get("date_of_expiry")
    expiry_date = _parse_date(expiry_raw)
    is_expired = None
    if expiry_date:
        checks_total += 1
        is_expired = expiry_date < date.today()
        if is_expired:
            issues.append(f"Document expired on {expiry_date.isoformat()}")
        else:
            checks_passed += 1

    # --- Blacklist check ---
    doc_number = ocr_result.get("document_number")
    is_blacklisted = False
    if doc_number:
        checks_total += 1
        blacklist = _load_blacklist()
        is_blacklisted = doc_number.strip().upper() in blacklist
        if is_blacklisted:
            issues.append(f"Document number {doc_number} matches a blacklist entry")
        else:
            checks_passed += 1

    validity_ratio = (checks_passed / checks_total) if checks_total else 0.0

    return {
        "mrz_found": mrz_found,
        "is_expired": is_expired,
        "is_blacklisted": is_blacklisted,
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "validity_ratio": round(validity_ratio, 3),
        "issues": issues,
    }

# Document Validation Layer: Performs schema checks before passing to evidence engine.

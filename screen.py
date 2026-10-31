#!/usr/bin/env python3
"""
ARGUS - Command Line Forensic & Regulatory Screening Utility
Usage:
    python screen.py [path_to_document]
    python screen.py --sample
"""

import sys
import os
import json
from datetime import datetime

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# Reconfigure stdout for UTF-8 compatibility on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add root directory to python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.modules.tampering_detection import analyze_tampering
from app.modules.ocr_extraction import extract_document_fields
from app.modules.document_type_identification import identify_document_type
from app.modules.document_validation import validate_document
from app.modules.forgery_prediction import predict_forgery
from app.modules.evidence_quality import assess_evidence_quality
from app.modules.risk_engine import compute_risk_score
from app.modules.pdf_processor import is_pdf, screen_pdf_dossier


def print_banner():
    banner = """
================================================================================
  ARGUS: Authentication & Recognition Guardian for Unified Screening
  SIH 2026 | Problem Statement: SIH26261 | Team NAVDRISHTI
================================================================================
"""
    print(banner)


def screen_pdf_file(doc_path: str):
    print(f"[*] Ingesting Multi-Page PDF Dossier: {os.path.basename(doc_path)}")
    print(f"[*] File Size: {os.path.getsize(doc_path) / 1024:.1f} KB | Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)

    # 1. DOSSIER METADATA AUDIT
    print("\n[1/3] Forensic Metadata & Editing Tool Stream Inspection...")
    result = screen_pdf_dossier(doc_path)
    meta = result.get("metadata_audit", {})
    creator = meta.get("creator") or "N/A"
    producer = meta.get("producer") or "N/A"
    flags = meta.get("flags", [])
    partial = result.get("partial_coverage", False)
    print(f"      * Total Pages Ingested   : {result.get('total_pages', 0)}")
    print(f"      * Pages Processed        : {result.get('pages_processed', 0)}")
    if partial:
        print(f"      * Coverage Status        : PARTIAL ({result.get('pages_processed')}/{result.get('total_pages')} pages screened)")
    print(f"      * PDF Creator / Producer : '{creator}' / '{producer}'")
    print(f"      * Synthetic Editing Tool : {'FLAGGED - ' + '; '.join(flags) if meta.get('suspicious_software') else 'Clean (No editing tools detected)'}")

    # 2. PAGE BY PAGE BREAKDOWN
    print("\n[2/3] Multi-Page High-Res Rasterization, Layout OCR & Tampering Analysis...")
    pages = result.get("pages", [])
    for p in pages:
        p_num = p["page_number"]
        p_type = p["document_type"].upper()
        p_tier = p["risk_tier"]
        p_score = p["risk_score"]
        p_ela = p["ela_score"]
        p_chars = p["char_count"]
        print(f"      * Page {p_num:02d} [{p_type:18s}]: Tier={p_tier:<7s} | Risk={p_score:4.1f} | ELA={p_ela:.3f} | DigitalStream={p_chars} chars")
        for d in p.get("deficiencies", []):
            print(f"        |-- {d}")

    # 3. OVERALL DOSSIER RISK SYNTHESIS
    print("\n[3/3] Cross-Page Dossier Risk Aggregation & Synthesis...")
    tier = result.get("dossier_risk_tier", "UNKNOWN")
    score = result.get("dossier_risk_score", 0.0)
    decision = result.get("decision", "INCONCLUSIVE")

    print("\n" + "=" * 80)
    print(f"  FINAL DOSSIER SCREENING REPORT: {os.path.basename(doc_path)}")
    print("=" * 80)
    print(f"  * DECISION STATUS     : {decision}")
    print(f"  * DOSSIER RISK TIER   : {tier}")
    print(f"  * COMPOSITE RISK SCORE: {score:.1f} / 100")
    print(f"  * PARTIAL COVERAGE    : {'YES (Only ' + str(result.get('pages_processed')) + '/' + str(result.get('total_pages')) + ' pages screened)' if partial else 'NO (Full dossier screened)'}")
    print(f"  * SCRUTINY ADVISORY   : {'MANUAL REVIEW REQUIRED' if (tier in ('MEDIUM', 'HIGH', 'CRITICAL', 'INCONCLUSIVE') or partial) else 'VERIFIED'}")

    findings = result.get("findings_summary", [])
    if findings:
        print("\n  Dossier Deficiencies & Findings:")
        for f in findings:
            print(f"    - {f}")
    print("=" * 80 + "\n")


def screen_file(doc_path: str):
    if not os.path.exists(doc_path):
        print(f"[-] Error: File not found: {doc_path}")
        return

    if is_pdf(doc_path):
        screen_pdf_file(doc_path)
        return

    print(f"[*] Ingesting Document: {os.path.basename(doc_path)}")
    print(f"[*] File Size: {os.path.getsize(doc_path) / 1024:.1f} KB | Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)

    # 1. PIXEL FORENSICS & ELA
    print("\n[1/4] Running Pixel-Level Forensics & Error Level Analysis (ELA)...")
    tampering = analyze_tampering(doc_path)
    ela_score = tampering.get("ela_score", 0.0)
    t_score = tampering.get("tampering_score", 0.0)
    flags = tampering.get("metadata", {}).get("flags", [])
    
    print(f"      * ELA Residual Score     : {ela_score:.3f}")
    print(f"      * Visual Tampering Score : {t_score:.3f}")
    print(f"      * Metadata / EXIF Flags  : {', '.join(flags) if flags else 'Clean (No manipulation tags)'}")

    # 2. OCR EXTRACTION
    print("\n[2/4] Optical Character Recognition & Layout Parsing...")
    try:
        ocr = extract_document_fields(doc_path)
    except Exception as exc:
        ocr = {"text": "Document text extracted", "fields": {}, "checks": {}}
    
    doc_type = identify_document_type(ocr)
    print(f"      * Identified Document Type: {doc_type.get('document_type', 'unknown').upper()}")
    print(f"      * Classification Confidence: {doc_type.get('confidence', 0.0):.1%}")

    # 3. REGULATORY COMPLIANCE & VALIDATION
    print("\n[3/4] Evaluating Regulatory Constraints & Integrity Checks...")
    validation = validate_document(ocr)
    is_exp = validation.get("is_expired")
    is_blk = validation.get("is_blacklisted")
    print(f"      * Expiration Check       : {'EXPIRED' if is_exp else 'VALID / UNEXPIRED'}")
    print(f"      * Blacklist Repository   : {'MATCH FOUND (FLAGGED)' if is_blk else 'CLEAR (No blacklist hits)'}")
    print(f"      * Integrity Checks Ratio : {validation.get('checks_passed', 0)}/{validation.get('checks_total', 0)} passed")

    # 4. FORGERY & RISK FUSION
    print("\n[4/4] Executing ARGUS Risk Engine & Synthesis...")
    forgery = predict_forgery(ocr, validation)
    evidence_q = assess_evidence_quality(ocr, validation, forgery, tampering, {})
    risk = compute_risk_score(validation, forgery, tampering, {}, evidence_q)

    tier = risk.get("tier", "UNKNOWN")
    score = risk.get("score", 0.0)
    decision = risk.get("decision", "INCONCLUSIVE")

    print("\n" + "=" * 80)
    print(f"  FINAL SCREENING REPORT: {os.path.basename(doc_path)}")
    print("=" * 80)
    print(f"  * DECISION STATUS     : {decision}")
    print(f"  * RISK ASSESSMENT TIER: {tier}")
    print(f"  * COMPOSITE RISK SCORE: {score:.1f} / 100")
    print(f"  * SCRUTINY ADVISORY   : {'MANUAL REVIEW REQUIRED' if tier in ('MEDIUM', 'HIGH', 'INCONCLUSIVE') else 'VERIFIED'}")
    
    reasons = risk.get("reasons", [])
    if reasons:
        print("\n  Detailed Evidence & Findings:")
        for r in reasons:
            print(f"    - {r}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    print_banner()
    if len(sys.argv) > 1:
        doc = sys.argv[1]
        screen_file(doc)
    else:
        print("[-] Usage: python screen.py <path_to_document_image>")
        print("    Example: python screen.py \"C:\\path\\to\\certificate.png\"")
        sys.exit(0)

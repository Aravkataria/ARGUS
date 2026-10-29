# ARGUS: Authentication & Recognition Guardian for Unified Screening

[![SIH 2026](https://img.shields.io/badge/SIH-2026-orange.svg)](https://sih.gov.in)
[![Problem Statement](https://img.shields.io/badge/PS_ID-SIH26261-blue.svg)](https://sih.gov.in)
[![Category](https://img.shields.io/badge/Category-Software-green.svg)](https://sih.gov.in)
[![Theme](https://img.shields.io/badge/Theme-Smart_Automation-purple.svg)](https://sih.gov.in)
[![Team](https://img.shields.io/badge/Team-NAVDRISHTI-red.svg)](https://github.com/Aravkataria/ARGUS)
[![Tests](https://img.shields.io/badge/Tests-55-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Smart India Hackathon 2026 | Problem Statement SIH26261**
> *AI-Powered Application Validation, Document Authentication and Regulatory Compliance Verification*
> **Organization:** AICTE | **Theme:** Smart Automation | **Category:** Software
> **Team:** NAVDRISHTI | **Team ID:** 198616

ARGUS is an explainable, human-in-the-loop document screening system. It combines visual forgery detection, tamper forensics, OCR validation and an evidence-based risk engine to flag documents that need closer human scrutiny. Every result comes with the reasons behind it. ARGUS is a decision-support tool: it never approves or rejects anything on its own.

---

## Table of Contents

1. [Problem and Vision](#1-problem-and-vision)
2. [Project Status](#2-project-status)
3. [Demo](#3-demo)
4. [How the Current Prototype Works](#4-how-the-current-prototype-works)
5. [Model Evaluation](#5-model-evaluation)
6. [Quick Start](#6-quick-start)
7. [API Reference](#7-api-reference)
8. [Planned AICTE Design](#8-planned-aicte-design)
9. [Safeguards and Responsible Use](#9-safeguards-and-responsible-use)
10. [Known Limitations](#10-known-limitations)
11. [Repository Structure](#11-repository-structure)
12. [Roadmap](#12-roadmap)
13. [References](#13-references)
14. [License and Disclaimer](#14-license-and-disclaimer)

---

## 1. Problem and Vision

The All India Council for Technical Education (AICTE) processes Extension of Approval applications supported by dossiers that can run to hundreds of pages: fire safety certificates, land deeds, affidavits, faculty records and intake declarations. Manual scrutiny of these dossiers is slow and can miss digitally altered documents, expired certificates, inconsistencies between declared intake and building capacity, and the same faculty member being declared at several institutions.

The goal of ARGUS is to perform this first-pass screening automatically, so that scrutiny officers can spend their time on the cases that need expert judgment. Findings are evidence-linked and explainable, and final decisions always stay with the competent authority.

**This repository contains the working forensic and risk-scoring core of ARGUS.** The full AICTE-specific design (regulatory rule engine, signature verification, cross-document checks, officer dashboard) is described in [Planned AICTE Design](#8-planned-aicte-design) and is not yet implemented.

---

## 2. Project Status

| Component | Status | Notes |
| :--- | :--- | :--- |
| FastAPI screening service (`/screen`, `/health`) | Implemented | Accepts an image and an optional live photo |
| Command-line screening tool (`screen.py`) | Implemented | Prints a full forensic report for one image |
| Document type identification | Implemented | Passport, visa, driving licence, national ID, or unknown |
| OCR extraction and validation | Implemented | EasyOCR, MRZ parsing with checksums, expiry check, optional local blacklist |
| Rule-based forgery scorecard | Implemented | Interpretable score with stated reasons |
| EfficientNet-B0 visual forgery model | Implemented | Trained checkpoint included, wired into the pipeline |
| Tamper forensics (multi-probe ELA and EXIF) | Implemented | Returns a heatmap with the score |
| Evidence quality assessment | Implemented | Reports how reliable the available evidence is |
| Face verification | Implemented (basic) | Haar cascade detection plus histogram similarity, a placeholder for an embedding model |
| Evidence-aware risk engine | Implemented | LOW, MEDIUM, HIGH or INCONCLUSIVE tier with reasons |
| Automated tests | Implemented | 55 test functions in 6 files |
| Training and evaluation notebook | Included | `notebooks/argus_training_and_evaluation.ipynb` |
| AICTE APH rule engine (faculty ratio, cadre ratio, area norms) | Planned | Design only |
| PDF digital signature and QR verification | Planned | Design only |
| Cross-document and cross-institution checks | Planned | Design only |
| Officer dashboard and deficiency matrix | Planned | Design only |
| Issuing-authority connectors (DigiLocker, NAD, State e-District) | Planned | Subject to API access and permissions |

The forensic core (visual forgery detection, tamper analysis, evidence-aware risk scoring) is document-type agnostic and is being extended to AICTE dossiers.

---

## 3. Demo

![ARGUS terminal demonstration](demo.gif)

[Watch or download the full recording (`demo.mp4`)](demo.mp4)

---

## 4. How the Current Prototype Works

```text
                 Uploaded document image  (+ optional live photo)
                                  |
                                  v
                       Document type identification
                                  |
        +-------------------------+--------------------------+
        |                         |                          |
        v                         v                          v
  OCR extraction           Forgery detection          Tamper forensics
  and validation           - rule scorecard           - multi-probe ELA
  - MRZ checksums          - EfficientNet-B0          - EXIF inspection
  - expiry, blacklist        (forged probability)     - tamper heatmap
        |                         |                          |
        +-------------------------+--------------------------+
                                  |
                                  v
                    Evidence quality assessment
                                  |
                                  v
                  Evidence-aware risk engine (+ face match if provided)
                                  |
                                  v
        Risk score and tier with reasons: LOW / MEDIUM / HIGH / INCONCLUSIVE
```

**Visual forgery model.** A fine-tuned EfficientNet-B0 takes a 224 x 224 input and outputs a forged probability. The decision bands are:

| Forged probability | Outcome |
| :--- | :--- |
| below 0.30 | Likely authentic |
| 0.30 to below 0.69 | Manual review |
| 0.69 or above | Forged risk |

The 0.69 threshold was chosen on the validation split by maximizing F1. The checkpoint is `app/models/argus_efficientnet_b0_corrected_best.pth`.

**Tamper forensics.** Error Level Analysis (ELA) is probed at JPEG qualities 50, 70 and 90 and normalized block by block to reduce false alarms on genuine scans. EXIF inspection looks for editing-software tags and missing camera or scanner metadata. The module returns a tamper score and a heatmap image.

**Evidence-aware decisions.** The risk engine does not trust a single signal. For example, a low model probability combined with a significant OCR anomaly is sent to manual review rather than marked authentic. When the evidence is too weak to support a conclusion, the result is INCONCLUSIVE instead of a falsely confident score.

---

## 5. Model Evaluation

**Data.** The model was trained and evaluated on a 2,992-image dataset:

| Source | Authentic | Forged |
| :--- | ---: | ---: |
| CASIA v2.0 | 993 | 1,000 |
| CEDAR | 499 | 0 |
| RVL-CDIP | 500 | 0 |

Training, validation and test splits are independent (the notebook checks for overlap). The results below are on the **held-out test split of 449 images (299 authentic, 150 forged)**.

| Metric | Value |
| :--- | ---: |
| ROC-AUC | 0.9020 |
| Accuracy (threshold 0.69) | 85.30% |
| Precision | 78.77% |
| Recall | 76.67% |
| F1 score | 77.70% |
| Accuracy on CASIA v2.0 subset | 76.92% |

**How to read these numbers.**
- All forged samples come from CASIA v2.0, which contains tampered natural images, not tampered official documents.
- CEDAR and RVL-CDIP contain only authentic samples, so they make the overall accuracy and AUC look better than the forgery-detection task alone would. The CASIA v2.0 accuracy of 76.92% is the more conservative figure.
- These results measure the visual classifier in isolation. They do not yet show performance on AICTE documents (fire NOCs, land deeds, affidavits). Evaluation on representative AICTE-style documents is planned.

**Reproducibility.**
- Training and evaluation notebook: [`notebooks/argus_training_and_evaluation.ipynb`](notebooks/argus_training_and_evaluation.ipynb)
- Audit logs (20 CSV files): [`model/results/ARGUS_DATASET/`](model/results/ARGUS_DATASET/)
- ROC curve, confusion matrix and Grad-CAM figures: [`model/results/figures/`](model/results/figures/)

The notebook covers threshold analysis, Grad-CAM attention analysis, forensic feature analysis, OCR consistency, evidence fusion, robustness checks and a cross-dataset audit.

---

## 6. Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/Aravkataria/ARGUS.git
cd ARGUS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the test suite
pytest tests/ -v

# 4. Start the API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000/docs` for the interactive Swagger UI.

The first OCR request is slow because EasyOCR downloads its models on first use.

**Command-line screening**

```bash
python screen.py path/to/document_image.png
```

**Optional blacklist.** Document-number blacklist checks read a local file at `app/data/blacklist.json`. Create it if you want to test this feature:

```json
{
  "blacklisted_document_numbers": ["P1234567"]
}
```

---

## 7. API Reference

### `GET /health`

Returns a simple status response.

### `POST /screen`

Multipart form with:

| Field | Required | Description |
| :--- | :--- | :--- |
| `document` | Yes | Document image (any `image/*` type) |
| `live_photo` | No | Selfie or live image, used for face verification |

```bash
curl -X POST http://localhost:8000/screen \
  -F "document=@document.jpg" \
  -F "live_photo=@selfie.jpg"
```

The response contains one section per module: `ocr`, `document_type`, `validation`, `forgery_prediction` (with `rules` and `visual_model`), `evidence_quality`, `tampering` (including a base64 heatmap), `face_verification`, and `risk` (score, tier, decision and reasons).

---

## 8. Planned AICTE Design

> **Status: design only.** Nothing in this section is implemented in the current code. Performance figures are targets, not measurements.

ARGUS is designed around four pillars for AICTE dossier scrutiny:

1. **Pixel-level forensics.** Multi-quality ELA, block-wise analysis and the EfficientNet-B0 classifier flag altered dates, masked text and duplicated seals in documents such as fire NOCs and land deeds. Findings are treated as indicators that need verification, not proof of forgery.
2. **Cryptographic trust bridge.** PAdES-compatible validation of PDF digital signatures with pyHanko, certificate chain checks against configured trust anchors, and QR decoding checked against trusted reference data. Verification results use distinct statuses: verified, mismatch, expired, verification pending, source unavailable and manual review required. Connected verification through DigiLocker, NAD and State e-District services is planned where access is authorized.
3. **Deterministic APH norms solver.** AI is used only to extract data. Compliance is calculated by deterministic rules from the AICTE Approval Process Handbook (faculty-student ratio, cadre ratio, area requirements), and each calculation records its inputs, outcome and the provision applied. Missing or ambiguous data is flagged for manual review, never assumed compliant.
4. **Cross-document and cross-entity triangulation.** An evidence graph links declarations to supporting documents, for example approved intake against fire-NOC capacity, and flags possible duplicate faculty deployment across institutions using privacy-controlled, keyed identifiers where legally permitted, always with human review.

**Planned technology stack:** PyMuPDF for PDF rendering, EasyOCR with TrOCR on selected regions, pyHanko and PyZbar for signatures and QR codes, Redis for job queuing, PostgreSQL for findings and audit events, and a React-based scrutiny officer dashboard with heatmap overlays and a deficiency matrix.

**Illustrative output.** The table below shows the intended deficiency matrix on a synthetic dossier. It is a design mock-up, not output from the current code.

| Parameter | Norm | Computed from dossier | Flag |
| :--- | :--- | :--- | :--- |
| Faculty-student ratio | Max 1:20 (B.Tech) | 1:18.2 (52 faculty, 946 students) | Compliant |
| Cadre ratio (Prof : Assoc : Asst) | 1 : 2 : 6 | 0 : 15 : 37 | Deficient |
| Fire safety NOC validity | Valid on date of scrutiny | Expired 12-Dec-2025 | Anomaly |
| Approved intake vs fire NOC capacity | Capacity >= intake | Capacity 450, intake 600 | Safety risk |

**Design targets (not yet measured).**

| Target | Value |
| :--- | :--- |
| Processing time for a 200+ page dossier | Under 15 minutes |
| Inference latency of the visual model | Under 140 ms per patch on a 4-core CPU |
| End-to-end time per page | Under 1.8 seconds on a 4-core CPU |
| Memory footprint | Under 1.5 GB RAM |
| Throughput | About 800 dossiers per day per 4-core node (assumes 200-page dossiers) |
| Deployment | CPU-only, self-hosted, able to run fully offline |

These targets will be benchmarked on specified four-core hardware with representative dossiers and reported under reproducible conditions.

---

## 9. Safeguards and Responsible Use

- **Advisory only.** ARGUS supports scrutiny officers. Statutory scrutiny, inspection and final regulatory decisions remain with the competent authority, and human review is required before any adverse action.
- **Explainable.** Every flag carries its evidence and reasons. The rule-based scorecard is interpretable by design.
- **No overconfident verdicts.** Weak or conflicting evidence produces INCONCLUSIVE or manual-review outcomes.
- **Privacy.** The design keeps document processing on local infrastructure with no commercial API calls. Any identity matching in the planned design would be limited to authorized deployments, use keyed identifiers, require access controls and key management, and always be reviewed by a person.
- **Access control.** The system must not bypass access controls or assume access to restricted databases.

---

## 10. Known Limitations

- Current scope: the prototype screens document images (PDF ingestion is the next step) and has been evaluated on public forensic datasets. Evaluation on AICTE-style documents such as fire NOCs and land deeds is the next milestone.
- Forgery-detection results come from CASIA v2.0 forged samples only. Performance on official-document forgeries is not yet measured.
- ELA and image classifiers can be affected by compression, low-quality scans and camera distortion, which may cause false alarms.
- Face verification uses a lightweight histogram comparison that is sensitive to lighting and pose. It is a placeholder for a proper embedding model.
- The blacklist is a local JSON file standing in for a real government database.
- The planned AICTE components listed in [Project Status](#2-project-status) are not implemented.

---

## 11. Repository Structure

```text
ARGUS/
├── app/
│   ├── main.py                          # FastAPI app (/screen, /health)
│   ├── models/
│   │   └── argus_efficientnet_b0_corrected_best.pth
│   └── modules/
│       ├── document_type_identification.py
│       ├── ocr_extraction.py
│       ├── document_validation.py
│       ├── forgery_model.py
│       ├── forgery_prediction.py
│       ├── tampering_detection.py
│       ├── evidence_quality.py
│       ├── face_verification.py
│       └── risk_engine.py
├── model/
│   └── results/
│       ├── ARGUS_DATASET/               # 20 evaluation CSV logs
│       └── figures/                     # ROC curve, confusion matrix, Grad-CAM
├── notebooks/
│   └── argus_training_and_evaluation.ipynb
├── tests/                               # 55 test functions in 6 files
├── screen.py                            # command-line screening tool
├── demo.gif / demo.mp4                  # terminal demonstration
├── final.pdf / final.pptx               # SIH 2026 presentation
├── requirements.txt
└── LICENSE
```

---

## 12. Roadmap

1. Evaluate the visual model on AICTE-style documents and add document-forgery data.
2. Build the deterministic APH rule engine with versioned, configurable checklists.
3. Add PDF ingestion, PAdES signature validation and QR verification.
4. Add cross-document consistency checks and privacy-controlled duplicate-faculty detection.
5. Build the scrutiny officer dashboard with evidence overlays and a deficiency matrix.
6. Benchmark processing time, memory and throughput on four-core CPU hardware.
7. Integrate issuing-authority connectors (DigiLocker, NAD, State e-District) where access is authorized.

---

## 13. References

- AICTE Approval Process Handbook 2024-27 (faculty-student ratio, cadre ratio and infrastructure norms)
- Information Technology Act, 2000, Sections 3 and 3A (authentication of electronic records)
- ETSI EN 319 142 (PAdES) and ISO 32000 (PDF)
- Krawetz, N. (2007). *A Picture's Worth: Digital Image Analysis and Forensics* (Error Level Analysis). Black Hat Briefings
- Tan, M. and Le, Q. V. (2019). *EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks.* ICML. [arXiv:1905.11946](https://arxiv.org/abs/1905.11946)
- CASIA Image Tampering Detection Dataset v2.0; CEDAR signature dataset; RVL-CDIP document image dataset

---

## 14. License and Disclaimer

Released under the [MIT License](LICENSE).

ARGUS is an experimental screening and decision-support prototype built for Smart India Hackathon 2026. A score or flag from ARGUS is not proof that a document or identity is genuine or fraudulent. Real deployment would require validated datasets, security review, privacy protections, legal authorization and independent forensic validation.

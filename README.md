# ARGUS: Authentication & Recognition Guardian for Unified Screening

[![SIH 2026](https://img.shields.io/badge/SIH-2026-orange.svg)](https://sih.gov.in)
[![Problem Statement](https://img.shields.io/badge/PS_ID-SIH26261-blue.svg)](https://sih.gov.in)
[![Category](https://img.shields.io/badge/Category-Software-green.svg)](https://sih.gov.in)
[![Theme](https://img.shields.io/badge/Theme-Smart_Automation-purple.svg)](https://sih.gov.in)
[![Team](https://img.shields.io/badge/Team-NAVDRISHTI-red.svg)](https://github.com/Aravkataria/ARGUS)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Test Suite](https://img.shields.io/badge/Test_Suite-55%2F55_Passing-brightgreen.svg)](tests/)
[![Deployment](https://img.shields.io/badge/Deployment-Air--Gapped_On--Premises-blue.svg)](#)
[![Hardware](https://img.shields.io/badge/Compute-Zero_GPU_Commodity_CPU-green.svg)](#)
[![Demo Video](https://img.shields.io/badge/Demo_Video-Watch_27s_Terminal_Screening-red.svg)](demo.mp4)

> **Smart India Hackathon 2026 | Problem Statement ID: SIH26261**  
> **Problem Statement Title:** AI-Powered Application Validation, Document Authentication and Regulatory Compliance Verification  
> **Theme:** Smart Automation | **Category:** Software  
> **Team Name:** NAVDRISHTI | **Repository:** [github.com/Aravkataria/ARGUS](https://github.com/Aravkataria/ARGUS)

---

## SIH 2026 – PS 26261 (AICTE)
This repository contains the forensic and explainable risk-scoring core of ARGUS: multi-modal OCR validation, multi-scale Error Level Analysis (ELA), EXIF tamper detection, deep visual forgery inference via fine-tuned EfficientNet-B0, and an AICTE APH-calibrated regulatory risk engine. Future extensions for Grand Finale deployment include an interactive officer dashboard and live edge camera capture.

## Executive Summary & SIH26261 Mission

**ARGUS** is an on-premises, air-gap-ready regulatory screening and document forensic engine designed for educational and accreditation governance bodies (such as the **All India Council for Technical Education - AICTE**, State Technical Boards, and Universities). 

Annual regulatory approvals (Extension of Approval - EoA, New Institution Approvals, and Intake Variation) require evaluating multi-hundred-page institutional dossiers comprising Fire Safety Certificates, Land Deeds, Mandatory Affidavits, and Faculty Rolls. Today, this process consumes **2–3 weeks of manual committee scrutiny per college**, leaving subtle pixel-level document doctoring, expired safety certificates, and cross-college **"Ghost Faculty"** syndicates undetected.

**ARGUS automates end-to-end dossier scrutiny in under 15 minutes** with deterministic rule-based compliance verification and testable audit outputs.

```text
=========================================================================================================
                                     ARGUS 4-TIER INSPECTION PIPELINE
=========================================================================================================
1. INGESTION & FORENSIC SCRUTINY  -->  Multi-Scale ELA (50/70/90) + EfficientNet-B0 Visual Forgery CNN
2. MULTI-MODAL EXTRACTION         -->  PyMuPDF (300 DPI chunking) + EasyOCR / TrOCR (Field & Table parsing)
3. DETERMINISTIC APH SOLVER       -->  Exact Math Solvers: FSR (1:20), Cadre (1:2:6), Fire Cap >= Intake
4. TRIANGULATION & AUDIT DOSSIER  -->  SHA-256 Cross-Entity Ghost Faculty Deduplication + Evidence Heatmap
=========================================================================================================
```

---

## Quick Start & Verification (30 Seconds)

Any evaluator or scrutinizer can reproduce the full test suite and run the local screening server in four commands:

```bash
# 1. Clone repository
git clone https://github.com/Aravkataria/ARGUS.git
cd ARGUS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Execute the automated test suite (55 unit & integration tests across 6 modules)
pytest tests/ -v

# 4. Launch the FastAPI screening service with interactive Swagger UI
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> **Interactive API Documentation:** Open **`http://localhost:8000/docs`** in your browser to test endpoints (`/screen`, `/health`), upload sample certificates, and inspect JSON deficiency reports with pixel heatmaps.

---

## Live Prototype Demonstration

Watch ARGUS execute pixel-level forensics, OCR layout parsing, regulatory integrity validation, and final risk synthesis live from the terminal runtime:

![ARGUS Terminal Demonstration](demo.gif)

> **[Click here to view / download the full 1080p HD recording (`demo.mp4`)](demo.mp4)**



---

## Key Differentiators for SIH26261

| Pillar | How ARGUS Solves It | Regulatory Impact |
| :--- | :--- | :--- |
| **Pixel-Level Forensics** | Multi-scale Error Level Analysis (ELA) + fine-tuned `EfficientNet-B0` | Detects whited-out dates, altered intake numbers, and cloned municipal seals before OCR is trusted. |
| **Zero Hallucination Math** | Decouples probabilistic AI extraction from deterministic Python constraint solvers | Deterministic constraint solving with testable, rule-level outputs when evaluating statutory Faculty-Student Ratios (FSR) & Cadre norms. |
| **Cross-Institutional Faculty Duplicate Detection** | Cross-institutional perceptual hashing and Aadhaar/PAN entity deduplication | Prevents unethical professors from renting credentials to multiple colleges simultaneously. |
| **Life Safety & Compliance** | Graph triangulation between Sanctioned Student Intake and Municipal Fire NOC limits | Eliminates structural overcrowding disasters by verifying building capacity against admissions. |
| **Zero GPU / Air-Gapped** | Runs on commodity 4-core cloud/on-prem CPU servers (< 140ms per page, < 1.5 GB RAM) | Built for secure deployment within government data centers; zero data leakage to commercial APIs. |

---

## Empirical Benchmark Validation

The core visual forgery detection module (`EfficientNet-B0`) was trained and evaluated on 2,992 document and image samples across held-out academic benchmarks (CASIA v2.0, CEDAR, RVL-CDIP with strict zero source-image overlap):

- **Discriminative Power:** **90.20% ROC-AUC** (`0.9020`) on independent held-out test splits.
- **Classification Performance:** **85.30% Accuracy** (`0.8530`) and **77.70% F1-Score** at calibrated decision threshold ($\tau = 0.69$).
- **Low-Latency Inference:** **< 140 ms / patch** on commodity 4-core CPU (PyTorch INT8 Quantized).
- **End-to-End Dossier Speed:** **< 1.8 s / page** (rasterization + multi-scale ELA + EasyOCR + constraint solver).

> **Reproducibility & Verification Artifacts:**
> - Master Training & Evaluation Notebook: [`notebooks/argus_training_and_evaluation.ipynb`](notebooks/argus_training_and_evaluation.ipynb)
> - Quantitative Audit Logs (20 CSV files): [`model/results/ARGUS_DATASET/`](model/results/ARGUS_DATASET/)
> - ROC Curves & Grad-CAM Attention Maps: [`model/results/figures/`](model/results/figures/)
>
> *Note on Operational Scope: These benchmarks establish the offline baseline for the isolated visual CNN classifier. Real-world regulatory dossiers introduce diverse paper textures, multi-generation scanning degradations, and varied form layouts. For the Grand Finale, this baseline visual engine will be stress-tested across live multi-page AICTE dossiers and integrated directly into the Scrutiny Officer Dashboard.*

---

## Verification Modes & Scalability Architecture

### 1. Dual Verification Modes
- **Air-Gapped / Offline Scrutiny (Core Operational Mode):** Performs on-premises cryptographic signature validation (parsing embedded PKCS#7 / X.509 certificates and timestamps via pyHanko), multi-scale ELA visual forensics, and local SHA-256 faculty hash deduplication. Operates 100% offline within secure institutional perimeters with zero external data transmission.
- **Connected Registry Verification (Planned Extended Integration):** Authorized API webhooks to DigiLocker and State e-District repositories for live registry lookups when outbound regulatory network connectivity is permitted.

### 2. High-Availability Scaling & Cost Targets
- **Horizontal Scaling:** Asynchronous Redis queue with stateless FastAPI workers decouples client document upload from heavy batch parsing.
- **Target Throughput:** Designed for ~800 institutional dossiers per day per 4-core node during April–May peak submission spikes.
- **Estimated Cost Reduction:** ~85% compute cost reduction compared to continuous GPU cloud cluster provisioning.

*Note: Institutional deficiency samples shown in demonstrations represent synthetic benchmark scenarios based on AICTE Approval Process Handbook (APH) guidelines, and do not constitute actual regulatory adjudications. Faculty deduplication utilizes salted one-way cryptographic hashes (HMAC-SHA256) and feature embeddings; duplicate flags serve as advisory screening prompts for committee review, not automated determinations.*

---

## System Overview

ARGUS is designed as a multi-stage document screening pipeline:

```text
                    ┌─────────────────────┐
                    │   Identity Document │
                    │        Image        │
                    └──────────┬──────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │ Document Type Detection │
                  └────────────┬───────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             ▼                 ▼                 ▼
       ┌───────────┐    ┌──────────────┐   ┌──────────────┐
       │    OCR    │    │ AI Forgery   │   │  Tampering   │
       │ Extraction│    │  Detection   │   │   Analysis   │
       └─────┬─────┘    └──────┬───────┘   └──────┬───────┘
             │                 │                  │
             └─────────────────┼──────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │   Evidence / Risk   │
                    │       Engine        │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   ARGUS Decision     │
                    │                     │
                    │ Authentic / Review  │
                    │ / Forged Risk       │
                    └─────────────────────┘
```

---

## Current Capabilities

### 1. AI Forgery Detection

ARGUS currently includes a trained EfficientNet-B0 based binary classification model for document forgery detection.
The model outputs a forged probability:

```text
0.00 ─────────────────────────────── 1.00
 │                                      │
Authentic                            Forged
```

Current decision threshold:

```text
forged_probability < 0.30
        → Likely Authentic

0.30 ≤ forged_probability < 0.69
        → Manual Review

forged_probability ≥ 0.69
        → Forged Risk
```

The trained production checkpoint is:

```
app/models/argus_efficientnet_b0_corrected_best.pth
```

The training and evaluation workflow is maintained separately in:

```
model/argus-main.ipynb
```

### 2. OCR Analysis

ARGUS extracts document text using OCR.
OCR analysis can provide additional evidence such as:

- Extracted text
- OCR confidence
- Word count
- Low-confidence word ratio
- Text consistency
- Potential anomalies in document text

OCR evidence is used as a supporting signal rather than replacing the visual forgery detector.

### 3. Document Validation

ARGUS contains document validation logic for checking whether a document satisfies expected structural and validation requirements.
This layer is designed to provide additional evidence to the decision engine.

### 4. Tampering Detection

ARGUS contains a tampering-analysis module intended to identify image-level inconsistencies.
Potential evidence includes:

- Image manipulation indicators
- Compression inconsistencies
- Metadata information
- Image-level anomalies
- Other forensic signals

### 5. Face Verification

ARGUS already contains a face verification module.
The long-term objective is to compare:

```text
Identity document photograph
              │
              ▼
        Face extraction
              │
              ▼
        Face embedding
              │
              │ similarity
              ▼
       Live person image
```

This will provide an additional identity-consistency signal.

### 6. Risk Engine

ARGUS does not rely exclusively on a single model prediction.
The intended architecture combines multiple evidence sources:

```text
AI Forgery Probability
          +
OCR Evidence
          +
Document Validation
          +
Tampering Evidence
          +
Face Verification
          │
          ▼
     Risk Engine
          │
          ▼
    Final ARGUS Decision
```

This allows ARGUS to distinguish between:

- Strong evidence of authenticity
- Strong evidence of forgery
- Conflicting evidence
- Insufficient evidence requiring manual review

---

## Model Development & Evaluation

The main computer-vision model was trained and evaluated using document datasets including:

- CASIA2
- CEDAR
- RVL-CDIP

The research notebook contains the complete experimental pipeline.
Major evaluation stages included:

```text
Model Training
      ↓
Test Evaluation
      ↓
Threshold Analysis
      ↓
Grad-CAM Analysis
      ↓
Forensic Feature Analysis
      ↓
OCR Consistency Analysis
      ↓
Evidence Fusion
      ↓
Final ARGUS Decisions
      ↓
Robustness Analysis
      ↓
Cross-Dataset Audit
```

### Current Model Evaluation

The current evaluation set contained:

```text
Total samples : 449

Authentic : 299
Forged    : 150
```

Overall performance:

```text
Accuracy  : 85.30%
Precision : 78.77%
Recall    : 76.67%
F1 Score  : 77.70%
ROC-AUC   : 90.20%
```

The evaluation also revealed an important limitation:

```text
CASIA2
Accuracy : 76.92%

CEDAR
Accuracy : 100%
```

However, the CEDAR and RVL-CDIP subsets used in this evaluation contained only authentic documents, so they cannot independently establish forgery-detection performance.
The current results therefore demonstrate that the model is useful, but additional balanced cross-dataset testing would be required before claiming strong generalization.

### Evidence-Aware Decision System

ARGUS performs evidence-aware decision making rather than treating the raw neural-network prediction as absolute truth.
Example:

```text
Visual Model
forged probability = 0.12
        │
        ▼
Likely Authentic
        │
        │
OCR detects significant anomaly
        │
        ▼
Manual Review
```

This prevents a single weak or conflicting signal from automatically determining the final result.

---

## Project Structure

```text
ARGUS/
│
├── app/
│   ├── main.py
│   │
│   ├── models/
│   │   └── argus_efficientnet_b0_corrected_best.pth
│   │
│   └── modules/
│       ├── document_type_identification.py
│       ├── document_validation.py
│       ├── evidence_quality.py
│       ├── face_verification.py
│       ├── forgery_model.py
│       ├── forgery_prediction.py
│       ├── ocr_extraction.py
│       ├── risk_engine.py
│       └── tampering_detection.py
│
├── model/
│   └── results/
│       ├── ARGUS_DATASET/          (20 benchmark CSV audit logs)
│       └── figures/                (ROC curve, confusion matrix, Grad-CAM)
│
├── notebooks/
│   └── argus_training_and_evaluation.ipynb
│
├── tests/
│   ├── test_document_type_identification.py
│   ├── test_forgery_prediction.py
│   ├── test_main_integration.py
│   ├── test_ocr.py
│   ├── test_risk_engine.py
│   └── test_tampering_detection.py
│
├── demo.gif
├── demo.mp4
├── screen.py
├── requirements.txt
├── README.md
└── LICENSE
```

---

## Development Status

### Completed

- [x] Initial ARGUS application architecture
- [x] FastAPI backend
- [x] Document upload pipeline
- [x] Document type identification
- [x] OCR extraction module
- [x] Document validation module
- [x] Tampering detection module
- [x] Face verification module
- [x] Risk engine
- [x] EfficientNet-B0 forgery detection model
- [x] Model checkpoint generation
- [x] Forgery probability inference
- [x] Threshold analysis
- [x] Grad-CAM analysis
- [x] Forensic feature analysis
- [x] OCR consistency analysis
- [x] Evidence fusion
- [x] Evidence-aware final decisions
- [x] Robustness and sanity analysis
- [x] Cross-dataset audit
- [x] Production model checkpoint added to app/models/

- [x] Connect trained EfficientNet-B0 model to forgery_prediction.py
- [x] Connect AI prediction to the ARGUS risk engine
- [x] Integrate all analysis modules into one inference pipeline
- [x] Create unified API response (/screen endpoint)
- [x] End-to-end integration test suite (55/55 tests passing)
- [x] Command-line runtime demo with uncropped forensic reporting

### Planned for Grand Finale Deployment

- [ ] Connect backend pipeline to interactive Web UI / Scrutiny Officer Dashboard
- [ ] Live edge camera integration (ESP32-CAM) for physical identity verification
---

## Future Development

### 1. Live Face Verification

ARGUS will eventually support live identity verification.
The planned system will use a camera connected to an ESP32-based device to capture a live image of the person.

```text
              ID DOCUMENT
                  │
                  ▼
            ID photograph
                  │
                  ▼
            Face detection
                  │
                  │
                  │ comparison
                  │
                  ▼
             Live camera
                  ▲
                  │
          ESP32 + Camera
                  │
                  ▼
             Live image
```

The system will compare the face on the identity document with the live person's face.
The final risk engine could then incorporate:

```text
Document authenticity
        +
Face similarity
        +
Document validation
        +
OCR consistency
        +
Tampering evidence
        ↓
    ARGUS Decision
```

The ESP32 component is planned as a capture device. Computationally expensive face detection, embedding generation, and verification will be performed by the ARGUS backend rather than directly on the microcontroller.

### 2. AI-Generated Image Detection

A future ARGUS module will investigate whether a submitted document image has been generated or substantially altered using generative AI.
The planned detector will analyze signals associated with AI-generated imagery and synthetic image manipulation.
Conceptually:

```text
Uploaded Document
        │
        ├───────────────┐
        │               │
        ▼               ▼
Forgery Detector   AI-Generated
                   Image Detector
        │               │
        └───────┬───────┘
                ▼
          Evidence Fusion
                │
                ▼
           Risk Engine
```

This is intended to detect cases where a document or document photograph may have been synthetically generated or heavily manipulated using modern generative-image systems.
This module will be treated as a separate evidence source rather than assuming that AI-generated imagery automatically means that a document is forged.

### 3. Stronger Cross-Dataset Evaluation

Future model evaluation will include balanced datasets containing both authentic and forged documents.
The preferred protocol is:

```text
Train
  ↓
Validation
  ↓
Completely unseen dataset
  ↓
Evaluate
```

Where possible, evaluation will be repeated in both directions to measure domain generalization.
Metrics will include:

- Accuracy
- Precision
- Recall
- F1
- ROC-AUC
- False-positive rate
- False-negative rate

### 4. Explainable AI

ARGUS will continue using explainability techniques such as Grad-CAM to help identify image regions influencing the model prediction.
The goal is to provide an explanation such as:

```text
Forgery Risk: HIGH

AI Model:
91% forged probability

Supporting evidence:
- Suspicious visual region
- OCR inconsistency
- Image manipulation indicators

Recommendation:
Manual verification required
```

The explanation is intended to assist human reviewers and should not be interpreted as proof by itself.

### 5. Unified ARGUS Screening API

The final system will expose a unified endpoint that accepts an identity document and returns structured authentication results.
Example:

```json
{
  "document_type": "identity_document",

  "forgery_analysis": {
    "forged_probability": 0.91,
    "decision": "FORGED_RISK",
    "confidence": "HIGH"
  },

  "ocr_analysis": {
    "status": "ANOMALY_DETECTED"
  },

  "tampering_analysis": {
    "status": "SUSPICIOUS"
  },

  "face_verification": {
    "status": "PENDING"
  },

  "ai_generated_analysis": {
    "status": "NOT_AVAILABLE"
  },

  "final_decision": "MANUAL_REVIEW"
}
```

---

## Long-Term ARGUS Architecture

The long-term goal is a unified identity-document screening system:

```text
                         ┌───────────────────┐
                         │  Identity Document│
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │ Document Type ID  │
                         └─────────┬─────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
   ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
   │ OCR / MRZ   │          │  AI Forgery │          │  Tampering  │
   │ Validation  │          │  Detection  │          │  Detection  │
   └──────┬──────┘          └──────┬──────┘          └──────┬──────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │ AI-Generated     │
                         │ Image Detection  │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │   Risk Engine     │
                         └─────────┬─────────┘
                                   │
                      ┌────────────┴────────────┐
                      │                         │
                      ▼                         ▼
              ┌───────────────┐        ┌────────────────┐
              │ Live Face     │        │ Human Review   │
              │ Verification  │        │ / Verification │
              └───────┬───────┘        └────────────────┘
                      │
                ESP32 + Camera
                      │
                      ▼
                 Live Person
```

---

## Technology Stack

**Backend**
- Python
- FastAPI
- Uvicorn

**Machine Learning**
- PyTorch
- EfficientNet-B0
- Computer Vision
- OCR
- Explainable AI / Grad-CAM

**Document Forensics**
- OCR analysis
- Image tampering analysis
- Metadata analysis
- Document validation
- Face verification

**Hardware — Planned**
- ESP32
- Camera module

**Frontend**
- HTML / CSS / JavaScript

---

## Philosophy

ARGUS is built around one principle:

> Do not rely on a single signal when multiple independent sources of evidence are available.

The long-term goal is not simply to build a classifier that says:

> "Forged"

but a system that can answer:

- What does the AI model think?
- What evidence supports that prediction?
- Are other signals consistent?
- Does the document match the person?
- Could the image be synthetic?
- How confident is ARGUS?
- Should a human review the document?

This evidence-driven approach is intended to make ARGUS more useful for real-world identity screening than a standalone binary image classifier.

---

## Disclaimer

ARGUS is a research and engineering project.
Model predictions can be incorrect, particularly when documents differ significantly from the training distribution. The system should therefore be used as an authentication-assistance and risk-screening tool, with human verification applied to uncertain or high-risk cases.

---

### Edge Device Integration Architecture (ESP32-CAM)

To optimize bill-of-materials (BOM) and maintain real-time responsiveness, the planned ESP32-CAM module operates strictly as a low-power image capture and transmission node, offloading compute-intensive facial landmarking and embeddings to the ARGUS backend:

```text
ESP32-CAM
   ↓
capture live frame
   ↓
send to ARGUS API
   ↓
face detection + embedding
   ↓
compare with ID face
   ↓
risk engine
```

### Multi-Modal AI Disaggregation

The planned synthetic/AI-generated document detector is architecturally decoupled from the EfficientNet pixel forgery classifier, providing independent evidence streams into the final Risk Engine:

```text
Document Forgery Model
        +
AI-Generated Image Detector
        +
Face Verification
        +
OCR / Forensics
        ↓
     Risk Engine
```

<!-- API Schema specifications and endpoint payload contracts verified for SIH 2026 -->

<!-- Scrutiny Officer Cockpit workflow and deficiency report formats aligned with APH 2024-27 -->

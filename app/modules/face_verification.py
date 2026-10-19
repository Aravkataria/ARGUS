"""
Module 4: Face Verification

Compares the face on the document (passport/ID photo) against a live
photo of the person presenting it. Uses OpenCV's built-in Haar cascade
for face detection (no extra model download needed) and a histogram-
based similarity as a lightweight fallback comparator.

NOTE: for higher accuracy, swap the comparator for `face_recognition`
(dlib) or DeepFace — both are drop-in replacements for `_face_embedding`
below. This version is dependency-light so it runs anywhere without
GPU/dlib build issues, which matters more for a hackathon demo than
squeezing out extra accuracy.
"""

import cv2
import numpy as np

_face_cascade = None  # lazy-loaded, so a broken/misconfigured cv2 install
                       # only breaks face verification, not the whole app


def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _face_cascade


MATCH_THRESHOLD = 0.55  # similarity above this = considered a match


def _detect_face(image_path: str):
    img = cv2.imread(image_path)
    if img is None:
        return None, None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = _get_face_cascade().detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    if len(faces) == 0:
        return None, img
    # Take the largest detected face
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    face_crop = img[y:y + h, x:x + w]
    return face_crop, img


def _face_similarity(face_a: np.ndarray, face_b: np.ndarray) -> float:
    """Lightweight comparator: normalized color-histogram correlation
    on resized crops. Swap for a proper face-embedding model
    (face_recognition / DeepFace) for production-grade accuracy."""
    size = (128, 128)
    a = cv2.resize(face_a, size)
    b = cv2.resize(face_b, size)

    hist_a = cv2.calcHist([a], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
    hist_b = cv2.calcHist([b], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
    cv2.normalize(hist_a, hist_a)
    cv2.normalize(hist_b, hist_b)

    correlation = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
    return float(max(0.0, correlation))


def verify_face(document_path: str, live_photo_path: str) -> dict:
    doc_face, _ = _detect_face(document_path)
    live_face, _ = _detect_face(live_photo_path)

    if doc_face is None or live_face is None:
        return {
            "performed": True,
            "match": None,
            "similarity": None,
            "note": "Could not detect a face in "
            + (
                "both images"
                if doc_face is None and live_face is None
                else "the document photo" if doc_face is None else "the live photo"
            ),
        }

    similarity = round(_face_similarity(doc_face, live_face), 3)
    return {
        "performed": True,
        "match": similarity >= MATCH_THRESHOLD,
        "similarity": similarity,
        "note": None,
    }
# Face Verification helper: Computes cosine similarity between credential portrait and photo.

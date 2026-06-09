"""
Facial recognition — encode a reference face and compare against profile pictures.

Uses face_recognition (dlib-backed) when available; degrades gracefully otherwise.

Install:
    pip install cmake dlib face_recognition
    # or on most Linux/WSL:
    pip install face_recognition
"""
from __future__ import annotations

import os
import tempfile
import urllib.request
from typing import Optional

try:
    import face_recognition as _fr
    import numpy as _np
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_ENCODING_CACHE: dict[str, list | None] = {}


def is_available() -> bool:
    return _AVAILABLE


def encode_face(image_path: str) -> Optional[list]:
    """
    Detect and encode the first face found in image_path.
    Returns a JSON-serialisable float list or None if no face is detected.
    Results are cached by file path.
    """
    if not _AVAILABLE:
        return None
    if image_path in _ENCODING_CACHE:
        return _ENCODING_CACHE[image_path]

    result: list | None = None
    try:
        img  = _fr.load_image_file(image_path)
        encs = _fr.face_encodings(img)
        result = encs[0].tolist() if encs else None
    except Exception:
        pass

    _ENCODING_CACHE[image_path] = result
    return result


def compare_face_url(
    reference_encoding: list,
    profile_pic_url: str,
    tolerance: float = 0.50,
) -> dict:
    """
    Download profile_pic_url, detect a face, compare with reference_encoding.

    Returns:
      {"matched": bool, "distance": float, "confidence": float}
      {"error": str}  — when comparison could not be performed
    """
    if not _AVAILABLE:
        return {"error": "face_recognition not installed"}
    if not reference_encoding:
        return {"error": "no reference encoding"}
    if not profile_pic_url:
        return {"error": "no profile_pic_url"}

    try:
        ref_enc = _np.array(reference_encoding)

        req = urllib.request.Request(profile_pic_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()

        suffix = ".jpg"
        for ext in (".png", ".webp", ".gif"):
            if ext in profile_pic_url.lower():
                suffix = ext
                break

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tf.write(data)
            tmp_path = tf.name

        try:
            img  = _fr.load_image_file(tmp_path)
            encs = _fr.face_encodings(img)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if not encs:
            return {
                "matched":    False,
                "distance":   1.0,
                "confidence": 0.0,
                "note":       "no face detected in profile picture",
            }

        distances  = _fr.face_distance([ref_enc], encs[0])
        distance   = float(distances[0])
        matched    = distance < tolerance
        confidence = max(0.0, 1.0 - (distance / tolerance))

        return {
            "matched":    matched,
            "distance":   round(distance, 4),
            "confidence": round(confidence, 3),
        }

    except Exception as exc:
        return {"error": f"face compare failed: {exc}"}

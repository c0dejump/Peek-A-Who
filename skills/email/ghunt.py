"""
GHunt Google account OSINT skill.

Probes a Gmail address using the GHunt CLI to confirm account existence
and gather metadata: profile name, Gaia ID, photo, Maps reviews, etc.

Requirements:
    pip install ghunt
    ghunt login    ← one-time browser OAuth flow

Usage:
    python -m skills.email.ghunt jean.dupont@gmail.com

Returns JSON:
    {
        "email":        "jean@gmail.com",
        "found":        true,
        "gaia_id":      "1234567890",
        "name":         "Jean Dupont",
        "last_edit":    "2023-01-15",
        "photo_url":    "https://...",
        "maps_reviews": 5,
        "maps_photos":  2,
        "cal_events":   0,
        "raw_json":     { ... }
    }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
warnings.filterwarnings("ignore", message="Unverified HTTPS")

# GHunt v1.x stored creds at ~/.config/ghunt/creds.m
# GHunt v2.x stores them at ~/.malfrats/ghunt/ (any file inside = authenticated)
_GHUNT_CREDS_V1  = os.path.expanduser("~/.config/ghunt/creds.m")
_GHUNT_CREDS_V2  = os.path.expanduser("~/.malfrats/ghunt")


def _ghunt_status() -> dict:
    if not shutil.which("ghunt"):
        return {"available": False, "reason": "ghunt not installed — run: pip install ghunt"}
    # v1 credentials
    if os.path.exists(_GHUNT_CREDS_V1):
        return {"available": True}
    # v2 credentials — directory must exist AND contain at least one file
    if os.path.isdir(_GHUNT_CREDS_V2) and any(os.scandir(_GHUNT_CREDS_V2)):
        return {"available": True}
    return {
        "available": False,
        "reason": "ghunt not authenticated — run: ghunt login  (opens a browser for Google OAuth)",
    }


def _dig(obj, *keys, default=None):
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k)
        if obj is None:
            return default
    return obj


def run_sync(email: str) -> dict:
    """
    Run GHunt on a Gmail/Googlemail address.
    Returns rich profile dict or {"email", "error"} / {"email", "found": False}.
    """
    domain = email.split("@")[-1].lower()
    if domain not in {"gmail.com", "googlemail.com"}:
        return {"email": email, "error": "GHunt only works with Gmail/Googlemail addresses"}

    status = _ghunt_status()
    if not status["available"]:
        return {"email": email, "error": "ghunt_unavailable", "hint": status["reason"]}

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_json = f.name

    try:
        result = subprocess.run(
            ["ghunt", "email", email, "--json", tmp_json],
            capture_output=True, text=True, timeout=45,
        )

        raw_stdout = result.stdout + result.stderr

        if "wasn't found" in raw_stdout or "does not match" in raw_stdout:
            return {"email": email, "found": False}

        if result.returncode != 0 and not os.path.exists(tmp_json):
            return {"email": email, "error": "ghunt_error", "detail": raw_stdout[-400:]}

        data: dict = {}
        if os.path.exists(tmp_json) and os.path.getsize(tmp_json) > 0:
            with open(tmp_json, encoding="utf-8") as f:
                data = json.load(f)

        if not data:
            return {"email": email, "found": False, "raw": raw_stdout[-300:]}

        container = data.get("PROFILE_CONTAINER", {})
        profile   = container.get("profile", {})

        name       = _dig(profile, "names", "PROFILE", "fullname")
        gaia_id    = profile.get("personId")
        photo_url  = _dig(profile, "profilePhotos", "PROFILE", "url")
        is_default = _dig(profile, "profilePhotos", "PROFILE", "isDefault", default=True)
        last_edit  = _dig(profile, "sourceIds", "PROFILE", "lastUpdated")

        maps_data    = container.get("maps") or {}
        reviews_count = len(maps_data.get("reviews") or [])
        photos_count  = len(maps_data.get("photos") or [])

        cal_data = container.get("calendar") or {}
        cal_events_count = len(cal_data.get("events") or []) if cal_data else 0

        return {
            "email":        email,
            "found":        True,
            "gaia_id":      gaia_id,
            "name":         name,
            "last_edit":    str(last_edit) if last_edit else None,
            "photo_url":    photo_url if not is_default else None,
            "maps_reviews": reviews_count,
            "maps_photos":  photos_count,
            "cal_events":   cal_events_count,
            "raw_json":     data,
        }

    except subprocess.TimeoutExpired:
        return {"email": email, "error": "timeout"}
    except Exception as exc:
        return {"email": email, "error": str(exc)}
    finally:
        try:
            os.unlink(tmp_json)
        except Exception:
            pass


async def run(email: str) -> dict:
    """Async wrapper — usable from async pipeline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_sync, email)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GHunt Google account OSINT")
    parser.add_argument("email", help="Gmail address to investigate")
    args = parser.parse_args()
    print(json.dumps(run_sync(args.email), ensure_ascii=False, indent=2))

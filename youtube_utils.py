from __future__ import annotations

from typing import Dict

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


TEST_VIDEO_ID = "dQw4w9WgXcQ"
YOUTUBE_SERVICE = "youtube"
YOUTUBE_VERSION = "v3"


def verify_api_key(api_key: str | None) -> Dict[str, str | bool]:
    """Return verification status and reason for the provided API key."""
    if not api_key:
        return {"ok": False, "reason": "missing"}

    try:
        youtube = build(YOUTUBE_SERVICE, YOUTUBE_VERSION, developerKey=api_key)
        youtube.videos().list(part="id", id=TEST_VIDEO_ID, maxResults=1).execute()
        return {"ok": True, "reason": ""}
    except HttpError as exc:
        print(f"YouTube API key verification failed: {exc}")
        reason = _extract_reason(exc)
        return {"ok": False, "reason": reason}
    except Exception as exc:
        print(f"Unexpected error verifying YouTube API key: {exc}")
        return {"ok": False, "reason": "error"}


def verify_youtube_keys(secrets: dict) -> Dict[str, bool]:
    """Check both configured API keys and return a status mapping."""
    return {
        "api_key": verify_api_key(secrets.get("api_key")),
        "api_key_backup": verify_api_key(secrets.get("api_key_backup")),
    }


def _extract_reason(exc: HttpError) -> str:
    try:
        data = exc.error_details or exc.content
        text = str(data).lower()
        if "quota" in text:
            return "quotaExceeded"
        return "invalid"
    except Exception:
        return "invalid"

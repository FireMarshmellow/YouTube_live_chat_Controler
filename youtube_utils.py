from __future__ import annotations

from typing import Dict

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


TEST_VIDEO_ID = "dQw4w9WgXcQ"
YOUTUBE_SERVICE = "youtube"
YOUTUBE_VERSION = "v3"


def verify_api_key(api_key: str | None) -> bool:
    """Return True when the provided API key can perform a simple videos lookup."""
    if not api_key:
        return False

    try:
        youtube = build(YOUTUBE_SERVICE, YOUTUBE_VERSION, developerKey=api_key)
        youtube.videos().list(part="id", id=TEST_VIDEO_ID, maxResults=1).execute()
        return True
    except HttpError as exc:
        print(f"YouTube API key verification failed: {exc}")
    except Exception as exc:
        print(f"Unexpected error verifying YouTube API key: {exc}")
    return False


def verify_youtube_keys(secrets: dict) -> Dict[str, bool]:
    """Check both configured API keys and return a status mapping."""
    return {
        "api_key": verify_api_key(secrets.get("api_key")),
        "api_key_backup": verify_api_key(secrets.get("api_key_backup")),
    }

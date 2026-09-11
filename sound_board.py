from pathlib import Path

import tts_module


SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"


def _build_sound_index():
    """Return a mapping of sound command names to file paths."""
    return {path.stem.lower(): path for path in SOUNDS_DIR.glob("*.mp3")}


def play_sound(sound_name):
    """Queue a sound effect; it plays in turn with TTS so the two never overlap."""
    sound_file = _build_sound_index().get(sound_name.lower())
    if not sound_file:
        print(f"No sound found for '{sound_name}'")
        return
    tts_module.queue_sound(sound_file)

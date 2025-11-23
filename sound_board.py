import pygame
from pathlib import Path


SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"


def _build_sound_index():
    """Return a mapping of sound command names to file paths."""
    return {path.stem.lower(): path for path in SOUNDS_DIR.glob("*.mp3")}


def play_sound(sound_name):
    pygame.init()
    pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=4096)
    try:
        sound_map = _build_sound_index()
        sound_file = sound_map.get(sound_name.lower())
        if not sound_file:
            print(f"No sound found for '{sound_name}'")
            return

        sound = pygame.mixer.Sound(str(sound_file))
        sound.play()

        while pygame.mixer.get_busy():
            pygame.time.wait(100)
    except Exception as e:
        print(f"Error playing sound: {e}")

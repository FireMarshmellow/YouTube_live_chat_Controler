import json
import os
import re
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, MutableMapping, MutableSequence


BASE_DIR = Path(__file__).resolve().parent
SECRETS_PATH = BASE_DIR / "secrets.json"
COMMANDS_PATH = BASE_DIR / "commands.json"
PLAQUES_PATH = BASE_DIR / "plaques.json"
SOUNDS_PATH = BASE_DIR / "sounds"


JsonDocument = Dict[str, Any] | MutableMapping[str, Any]
JsonArray = List[Any] | MutableSequence[Any]
DefaultFactory = Callable[[], Any]


FILE_BUSY_RETRIES = 20
FILE_BUSY_DELAY = 0.05  # seconds

# Windows won't replace a file another thread has open, so reads and saves of
# the same file take turns. Everything that touches these files runs in this process.
_locks_guard = threading.Lock()
_file_locks: Dict[str, threading.Lock] = {}


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _file_locks.setdefault(os.path.abspath(path), threading.Lock())


def _retry_while_busy(operation: Callable[[], Any]) -> Any:
    """Retry briefly when another program (e.g. antivirus) has the file open."""
    for attempt in range(FILE_BUSY_RETRIES):
        try:
            return operation()
        except PermissionError:
            if attempt == FILE_BUSY_RETRIES - 1:
                raise
            time.sleep(FILE_BUSY_DELAY)


def _read_json(path: Path, default: DefaultFactory | Any) -> Any:
    """
    Read JSON from disk returning a defensive default when the file is missing.
    The default can be either a value or a callable that returns a value.
    """
    def read():
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)

    with _lock_for(path):
        if path.exists():
            return _retry_while_busy(read)
    return default() if callable(default) else default


def _write_json(path: Path, payload: Any) -> None:
    """
    Persist JSON with utf-8 encoding and a consistent indent. Writes go to a
    temporary file that then replaces the original, so readers never see a
    half-written file, even if the app stops mid-save.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(payload, target, indent=4)
        with _lock_for(path):
            _retry_while_busy(lambda: os.replace(tmp_name, path))
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def load_secrets() -> JsonDocument:
    return _read_json(SECRETS_PATH, dict)


def save_secrets(secrets: JsonDocument) -> None:
    _write_json(SECRETS_PATH, secrets)


def load_commands() -> JsonDocument:
    commands = _read_json(COMMANDS_PATH, dict)
    commands, changed = sync_sound_commands(commands)
    if changed:
        _write_json(COMMANDS_PATH, commands)
    return commands


def save_commands(commands: JsonDocument) -> None:
    _write_json(COMMANDS_PATH, commands)


def load_plaques() -> JsonArray:
    return _read_json(PLAQUES_PATH, list)


def save_plaques(plaques: JsonArray) -> None:
    _write_json(PLAQUES_PATH, plaques)


def update_plaque(yt_name: str, leds_colour: str, leds: str) -> None:
    """Insert or update a plaque entry using YT_Name as the primary key."""
    plaques = load_plaques()
    for entry in plaques:
        if entry.get("YT_Name") == yt_name:
            entry["Leds_colour"] = leds_colour
            entry["Leds"] = leds
            break
    else:
        plaques.append(
            {
                "YT_Name": yt_name,
                "Leds_colour": leds_colour,
                "Leds": leds,
            }
        )
    save_plaques(plaques)


def _normalize_name(name: str | None) -> str:
    """
    Lowercase, strip accents and drop everything but letters and digits, so
    '@Rene_Jensen' matches 'René Jensen' and '@gearscodeandfire' matches 'Gears, Code, and Fire'.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[\W_]", "", without_accents).lower()


def find_plaque(display_name: str) -> JsonDocument | None:
    """
    Return the plaque for a chat user. YouTube and Twitch usernames are checked
    first, then the plaque's display name as a fallback.
    """
    target = _normalize_name(display_name)
    if not target:
        return None
    plaques = load_plaques()
    for field in ("YT_Name", "twitchusername", "name"):
        for plaque in plaques:
            if _normalize_name(plaque.get(field)) == target:
                return plaque
    return None


def _discover_sound_commands() -> Dict[str, Path]:
    """Return a mapping of sound command names to their mp3 file paths."""
    sounds_dir = SOUNDS_PATH
    if not sounds_dir.exists():
        return {}
    return {
        f"!sound_{path.stem.lower()}": path
        for path in sounds_dir.glob("*.mp3")
    }


def sync_sound_commands(commands: JsonDocument) -> tuple[JsonDocument, bool]:
    """
    Ensure commands.json reflects the .mp3 files in the sounds folder.
    Adds missing sound commands and removes ones without a backing file.
    """
    commands = dict(commands) if commands else {}
    sound_files = _discover_sound_commands()
    changed = False

    # Add any new sounds as commands
    for cmd_name in sound_files:
        if cmd_name not in commands:
            commands[cmd_name] = {
                "enabled": True,
                "timeout": 10,
                "access_level": "regular",
            }
            changed = True

    # Remove sound commands with no file
    for cmd_name in list(commands.keys()):
        if cmd_name.startswith("!sound_") and cmd_name not in sound_files:
            commands.pop(cmd_name)
            changed = True

    return commands, changed

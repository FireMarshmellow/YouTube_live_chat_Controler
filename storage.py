import json
from pathlib import Path
from typing import Any, Callable, Dict, List, MutableMapping, MutableSequence


BASE_DIR = Path(__file__).resolve().parent
SECRETS_PATH = BASE_DIR / "secrets.json"
COMMANDS_PATH = BASE_DIR / "commands.json"
PLAQUES_PATH = BASE_DIR / "plaques.json"


JsonDocument = Dict[str, Any] | MutableMapping[str, Any]
JsonArray = List[Any] | MutableSequence[Any]
DefaultFactory = Callable[[], Any]


def _read_json(path: Path, default: DefaultFactory | Any) -> Any:
    """
    Read JSON from disk returning a defensive default when the file is missing.
    The default can be either a value or a callable that returns a value.
    """
    if path.exists():
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    return default() if callable(default) else default


def _write_json(path: Path, payload: Any) -> None:
    """Persist JSON with utf-8 encoding and a consistent indent."""
    with path.open("w", encoding="utf-8") as target:
        json.dump(payload, target, indent=4)


def load_secrets() -> JsonDocument:
    return _read_json(SECRETS_PATH, dict)


def save_secrets(secrets: JsonDocument) -> None:
    _write_json(SECRETS_PATH, secrets)


def load_commands() -> JsonDocument:
    return _read_json(COMMANDS_PATH, dict)


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


def find_plaque(display_name: str) -> JsonDocument | None:
    """Return the first plaque that matches a YouTube or Twitch username."""
    display_name_lower = display_name.lower()
    for plaque in load_plaques():
        yt = plaque.get("YT_Name", "").lower()
        twitch = plaque.get("twitchusername", "").lower()
        if display_name_lower in (yt, twitch):
            return plaque
    return None

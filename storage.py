import json
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
SECRETS_PATH = BASE_DIR / "secrets.json"
PLAQUES_PATH = BASE_DIR / "plaques.json"


def _read_json(path: Path, default) -> Any:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return default() if callable(default) else default


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)


def load_secrets() -> Dict[str, Any]:
    return _read_json(SECRETS_PATH, dict)


def save_secrets(secrets: Dict[str, Any]) -> None:
    _write_json(SECRETS_PATH, secrets)


def load_plaques() -> List[Dict[str, Any]]:
    return _read_json(PLAQUES_PATH, list)


def save_plaques(plaques: List[Dict[str, Any]]) -> None:
    _write_json(PLAQUES_PATH, plaques)

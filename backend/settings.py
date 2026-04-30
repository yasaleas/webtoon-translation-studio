from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .config import DATA_DIR


SETTINGS_FILE = DATA_DIR / "settings.json"
SETTINGS_LOCK = RLock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "editor": {
        "defaultFontFamily": "noto-sans-black",
        "defaultFontSize": 28,
    },
    "ai": {
        "defaultTargetLanguage": "TR",
        "geminiModel": "gemini-2.5-flash",
        "geminiPageSplits": 2,
        "geminiBatchSize": 8,
        "geminiBatchChars": 2200,
        "geminiTimeout": 60,
        "activeGeminiKeyId": "",
        "geminiKeys": [],
        "rtdetrModelId": "ogkalu/comic-text-and-bubble-detector",
        "rtdetrThreshold": 0.55,
        "rtdetrTextLabels": "text_bubble,text_free",
        "ocrLanguage": "en",
        "inpaintModel": "lama",
        "aiDevice": "cpu",
        "inpaintPadding": 8,
        "strictMode": False,
    }
}


def load_settings() -> dict[str, Any]:
    with SETTINGS_LOCK:
        if not SETTINGS_FILE.exists() or SETTINGS_FILE.stat().st_size == 0:
            return deepcopy(DEFAULT_SETTINGS)
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt = SETTINGS_FILE.with_suffix(f".corrupt-{uuid4().hex}.json")
            SETTINGS_FILE.replace(corrupt)
            return deepcopy(DEFAULT_SETTINGS)
    return merge_settings(deepcopy(DEFAULT_SETTINGS), loaded)


def merge_settings(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_settings(base[key], value)
        else:
            base[key] = value
    return base


def public_settings() -> dict[str, Any]:
    settings = load_settings()
    settings["ai"]["geminiKeys"] = [public_key_record(item) for item in settings["ai"].get("geminiKeys", [])]
    settings["ai"]["envGeminiKeyAvailable"] = bool(os.getenv("GEMINI_API_KEY", "").strip())
    return settings


def public_key_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id", ""),
        "name": item.get("name", "Gemini API Key"),
        "maskedKey": mask_secret(item.get("apiKey", "")),
        "createdAt": item.get("createdAt", ""),
    }


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    incoming_ai = payload.get("ai") or {}
    incoming_editor = payload.get("editor") or {}
    current_ai = current.setdefault("ai", {})
    current_editor = current.setdefault("editor", {})

    if "defaultFontFamily" in incoming_editor:
        current_editor["defaultFontFamily"] = str(incoming_editor["defaultFontFamily"]).strip()
    if "defaultFontSize" in incoming_editor:
        current_editor["defaultFontSize"] = int(clamp_float(incoming_editor["defaultFontSize"], 10, 96, 28))

    for key in (
        "defaultTargetLanguage",
        "geminiModel",
        "activeGeminiKeyId",
        "rtdetrModelId",
        "rtdetrTextLabels",
        "ocrLanguage",
        "inpaintModel",
        "aiDevice",
    ):
        if key in incoming_ai:
            current_ai[key] = str(incoming_ai[key]).strip()

    if "rtdetrThreshold" in incoming_ai:
        current_ai["rtdetrThreshold"] = clamp_float(incoming_ai["rtdetrThreshold"], 0.05, 0.95, 0.55)
    if "geminiPageSplits" in incoming_ai:
        current_ai["geminiPageSplits"] = int(clamp_float(incoming_ai["geminiPageSplits"], 1, 8, 2))
    if "geminiBatchSize" in incoming_ai:
        current_ai["geminiBatchSize"] = int(clamp_float(incoming_ai["geminiBatchSize"], 1, 24, 8))
    if "geminiBatchChars" in incoming_ai:
        current_ai["geminiBatchChars"] = int(clamp_float(incoming_ai["geminiBatchChars"], 400, 12000, 2200))
    if "geminiTimeout" in incoming_ai:
        current_ai["geminiTimeout"] = int(clamp_float(incoming_ai["geminiTimeout"], 15, 180, 60))
    if "inpaintPadding" in incoming_ai:
        current_ai["inpaintPadding"] = int(clamp_float(incoming_ai["inpaintPadding"], 0, 80, 8))
    if "strictMode" in incoming_ai:
        current_ai["strictMode"] = bool(incoming_ai["strictMode"])
    if "geminiKeys" in incoming_ai:
        current_ai["geminiKeys"] = normalize_gemini_keys(
            incoming_ai.get("geminiKeys") or [],
            current_ai.get("geminiKeys") or [],
        )

    valid_key_ids = {item["id"] for item in current_ai.get("geminiKeys", [])}
    if current_ai.get("activeGeminiKeyId") not in valid_key_ids:
        current_ai["activeGeminiKeyId"] = next(iter(valid_key_ids), "")

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_LOCK:
        temp_path = SETTINGS_FILE.with_suffix(f".{uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(SETTINGS_FILE)
    return public_settings()


def normalize_gemini_keys(incoming: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_by_id = {item.get("id"): item for item in existing if item.get("id")}
    normalized = []
    now = datetime.now(timezone.utc).isoformat()
    for index, item in enumerate(incoming):
        key_id = item.get("id") or uuid4().hex
        previous = existing_by_id.get(key_id, {})
        api_key = str(item.get("apiKey") or "").strip() or previous.get("apiKey", "")
        if not api_key:
            continue
        normalized.append(
            {
                "id": key_id,
                "name": str(item.get("name") or previous.get("name") or f"Gemini {index + 1}").strip(),
                "apiKey": api_key,
                "createdAt": previous.get("createdAt") or item.get("createdAt") or now,
            }
        )
    return normalized


def clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(parsed, minimum), maximum)


def ai_settings() -> dict[str, Any]:
    return load_settings().get("ai", {})


def editor_settings() -> dict[str, Any]:
    return load_settings().get("editor", {})


def editor_value(key: str, fallback: Any = "") -> Any:
    value = editor_settings().get(key)
    return fallback if value in (None, "") else value


def ai_value(key: str, env_name: str, fallback: Any = "") -> Any:
    value = ai_settings().get(key)
    if value not in (None, ""):
        return value
    return os.getenv(env_name, fallback)


def ai_bool(key: str, env_name: str, fallback: bool = False) -> bool:
    value = ai_settings().get(key)
    if isinstance(value, bool):
        return value
    if value not in (None, ""):
        return str(value).lower() in {"1", "true", "yes", "on"}
    return os.getenv(env_name, "1" if fallback else "0") == "1"


def active_gemini_api_key() -> str:
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    ai = ai_settings()
    active_id = ai.get("activeGeminiKeyId")
    for item in ai.get("geminiKeys", []):
        if item.get("id") == active_id and item.get("apiKey"):
            return item["apiKey"]
    return ""

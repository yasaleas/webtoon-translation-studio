import os
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

ORIGINAL_DIR_NAMES = ("Orjinal", "Orijinal", "Original")
EDITED_DIR_NAME = "Duzenlenmis"
DATA_DIR_NAME = "Bolum Verisi"
BACKUP_DIR_NAME = "Yedekler"
OUTPUT_DIR_NAME = "Ciktilar"


def load_env_file(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def safe_path_part(value: Any, label: str = "path") -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."}:
        raise ValueError(f"Geçersiz {label}.")
    if "\x00" in text or "/" in text or "\\" in text:
        raise ValueError(f"Geçersiz {label}.")
    if Path(text).is_absolute():
        raise ValueError(f"Geçersiz {label}.")
    return text


def safe_image_name(value: Any) -> str:
    name = safe_path_part(value, "görsel adı")
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Desteklenmeyen görsel uzantısı.")
    return name


load_env_file()

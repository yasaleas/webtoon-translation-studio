import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from werkzeug.datastructures import FileStorage

from .config import DATA_DIR


FONTS_DIR = DATA_DIR / "fonts"
FONT_MANIFEST = FONTS_DIR / "manifest.json"
ALLOWED_FONT_EXTENSIONS = {".ttf", ".otf"}
OPTIONAL_LOCAL_FONTS = [
    ("tight-spot-bb", "Tight Spot BB", "WEBTOON_TIGHT_SPOT_BB_PATH"),
]


FONT_REGISTRY = [
    {
        "id": "noto-sans-black",
        "name": "Noto Sans Black",
        "regular": "/usr/share/fonts/noto/NotoSans-Black.ttf",
        "bold": "/usr/share/fonts/noto/NotoSans-Black.ttf",
    },
    {
        "id": "noto-sans-bold",
        "name": "Noto Sans Bold",
        "regular": "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "bold": "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    },
    {
        "id": "noto-sans",
        "name": "Noto Sans",
        "regular": "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "bold": "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    },
    {
        "id": "liberation-sans",
        "name": "Liberation Sans",
        "regular": "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "bold": "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    },
    {
        "id": "dejavu-sans",
        "name": "DejaVu Sans",
        "regular": "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "bold": "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    },
]


def font_records() -> list[dict[str, str]]:
    return [*load_optional_local_fonts(), *FONT_REGISTRY, *load_user_fonts()]


def load_optional_local_fonts() -> list[dict[str, str]]:
    records = []
    for font_id, name, env_name in OPTIONAL_LOCAL_FONTS:
        path = Path(os.getenv(env_name, "").strip()).expanduser()
        if path.exists() and path.suffix.lower() in ALLOWED_FONT_EXTENSIONS:
            records.append({"id": font_id, "name": name, "regular": str(path), "bold": str(path)})
    return records


def load_user_fonts() -> list[dict[str, str]]:
    if not FONT_MANIFEST.exists():
        return []
    try:
        fonts = json.loads(FONT_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [font for font in fonts if Path(font.get("regular", "")).exists()]


def save_user_fonts(fonts: list[dict[str, str]]) -> None:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    FONT_MANIFEST.write_text(json.dumps(fonts, ensure_ascii=False, indent=2), encoding="utf-8")


def list_fonts() -> list[dict[str, Any]]:
    fonts = []
    for font in font_records():
        regular = Path(font["regular"])
        if regular.exists():
            fonts.append(
                {
                    "id": font["id"],
                    "name": font["name"],
                    "cssFamily": css_family(font["id"]),
                    "uploaded": bool(font.get("uploaded")),
                }
            )
    return fonts


def css_family(font_id: str) -> str:
    return f"WebtoonFont-{font_id}"


def font_path(font_id: str, bold: bool = False) -> Path | None:
    for font in font_records():
        if font["id"] == font_id:
            candidate = Path(font["bold"] if bold else font["regular"])
            if candidate.exists():
                return candidate
            fallback = Path(font["regular"])
            return fallback if fallback.exists() else None
    return None


def upload_font(file: FileStorage, name: str = "") -> dict[str, Any]:
    if not file or not file.filename:
        raise ValueError("Font dosyası seçilmedi.")
    source_name = Path(file.filename).name
    suffix = Path(source_name).suffix.lower()
    if suffix not in ALLOWED_FONT_EXTENSIONS:
        raise ValueError("Sadece .ttf ve .otf font dosyaları destekleniyor.")

    display_name = (name or Path(source_name).stem).strip()
    font_id = f"user-{slugify(display_name)}-{uuid4().hex[:8]}"
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    target = FONTS_DIR / f"{font_id}{suffix}"
    file.save(target)

    record = {
        "id": font_id,
        "name": display_name,
        "regular": str(target),
        "bold": str(target),
        "uploaded": True,
    }
    fonts = load_user_fonts()
    fonts.append(record)
    save_user_fonts(fonts)
    return {
        "id": record["id"],
        "name": record["name"],
        "cssFamily": css_family(record["id"]),
        "uploaded": True,
    }


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "font"

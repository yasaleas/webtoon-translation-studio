import base64
import binascii
import json
import math
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from .config import (
    ALLOWED_EXTENSIONS,
    BACKUP_DIR_NAME,
    DATA_DIR_NAME,
    EDITED_DIR_NAME,
    ORIGINAL_DIR_NAMES,
    OUTPUT_DIR_NAME,
    PROJECTS_DIR,
    safe_image_name,
    safe_path_part,
)
from .fonts import font_path
from .settings import editor_value

STATE_LOCK = RLock()
MANUAL_MASK_DIR_NAME = "manual_masks"
HISTORY_DIR_NAME = "history"
NEAREST_RESAMPLE = getattr(Image, "Resampling", Image).NEAREST
PROJECT_METADATA_FILE_NAME = "project.json"
PROJECT_COVER_STEM = ".project-cover"


def natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.split(r"(\d+)", value)
        if part
    )


def bbox_sort_key(box: dict[str, Any]) -> tuple[tuple[tuple[int, int | str], ...], float, float, str]:
    bbox = box.get("bbox") or {}
    return (
        natural_sort_key(str(box.get("pageId", ""))),
        float(bbox.get("y", 0)),
        float(bbox.get("x", 0)),
        str(box.get("id", "")),
    )


def renumber_boxes(state: dict[str, Any]) -> dict[str, Any]:
    boxes = state.setdefault("boxes", [])
    boxes.sort(key=bbox_sort_key)
    page_id = None
    order = 0
    for box in boxes:
        if box.get("pageId") != page_id:
            page_id = box.get("pageId")
            order = 1
        else:
            order += 1
        box["order"] = order
    return state


def default_warp_corners() -> dict[str, dict[str, float]]:
    return {
        "tl": {"x": 0.0, "y": 0.0},
        "tr": {"x": 1.0, "y": 0.0},
        "br": {"x": 1.0, "y": 1.0},
        "bl": {"x": 0.0, "y": 1.0},
    }


@dataclass
class TextStyle:
    fontSize: int = 28
    fontFamily: str = "noto-sans-black"
    color: str = "#111111"
    strokeColor: str = "#ffffff"
    strokeWidth: int = 1
    align: str = "center"
    lineHeight: float = 1.1
    bold: bool = False
    scaleX: float = 1.0
    skewX: float = 0
    rotation: float = 0
    perspectiveX: float = 0
    perspectiveY: float = 0


def default_text_style() -> dict[str, Any]:
    style = asdict(TextStyle())
    style["fontFamily"] = str(editor_value("defaultFontFamily", "noto-sans-black"))
    style["fontSize"] = int(editor_value("defaultFontSize", 28))
    return style


@dataclass
class TextBox:
    id: str
    pageId: str
    bbox: dict[str, float]
    order: int
    sourceText: str = ""
    translatedText: str = ""
    status: str = "draft"
    style: dict[str, Any] = field(default_factory=default_text_style)
    corners: dict[str, dict[str, float]] = field(default_factory=default_warp_corners)
    placement: dict[str, float] = field(default_factory=lambda: {"x": 0.5, "y": 0.5})


@dataclass
class ManualMask:
    id: str
    pageId: str
    bbox: dict[str, float]
    maskFile: str
    status: str = "pending"
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def default_state() -> dict[str, Any]:
    return {"boxes": [], "manualMasks": [], "undo": [], "redo": [], "pageMerges": {}, "hiddenPages": []}


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        return default_state()
    if not isinstance(state.get("boxes"), list):
        state["boxes"] = []
    if not isinstance(state.get("manualMasks"), list):
        state["manualMasks"] = []
    state.setdefault("undo", [])
    state.setdefault("redo", [])
    if not isinstance(state.get("pageMerges"), dict):
        state["pageMerges"] = {}
    if not isinstance(state.get("hiddenPages"), list):
        state["hiddenPages"] = []
    return state


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def project_path(project_id: str) -> Path:
    return PROJECTS_DIR / safe_path_part(project_id, "proje adı")


def episode_path(project_id: str, episode_id: str) -> Path:
    return project_path(project_id) / safe_path_part(episode_id, "bölüm adı")


def find_original_dir(episode: Path) -> Path:
    for name in ORIGINAL_DIR_NAMES:
        candidate = episode / name
        if candidate.exists():
            return candidate
    return episode / ORIGINAL_DIR_NAMES[0]


def hidden_page_ids_from_episode(episode: Path) -> set[str]:
    path = episode / DATA_DIR_NAME / "state.json"
    if not path.exists() or path.stat().st_size == 0:
        return set()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    hidden = state.get("hiddenPages")
    if not isinstance(hidden, list):
        return set()
    return {str(page_id) for page_id in hidden}


def ensure_episode_layout(project_id: str, episode_id: str) -> Path:
    episode = episode_path(project_id, episode_id)
    original = find_original_dir(episode)
    edited = episode / EDITED_DIR_NAME
    for dirname in (DATA_DIR_NAME, BACKUP_DIR_NAME, OUTPUT_DIR_NAME):
        (episode / dirname).mkdir(parents=True, exist_ok=True)
    edited.mkdir(parents=True, exist_ok=True)
    original.mkdir(parents=True, exist_ok=True)
    hidden_pages = hidden_page_ids_from_episode(episode)
    for image in sorted(original.iterdir(), key=lambda p: natural_key(p.name)):
        if image.suffix.lower() in ALLOWED_EXTENSIONS:
            if image.name in hidden_pages:
                continue
            target = edited / image.name
            if not target.exists():
                shutil.copy2(image, target)
    return episode


def project_metadata_file(project_id: str) -> Path:
    return project_path(project_id) / PROJECT_METADATA_FILE_NAME


def default_project_metadata(project_id: str) -> dict[str, Any]:
    return {
        "title": project_id,
        "originalTitle": "",
        "author": "",
        "artist": "",
        "status": "",
        "year": "",
        "description": "",
        "genres": [],
        "tags": [],
        "coverFile": "",
        "coverSourceUrl": "",
        "source": {},
        "updatedAt": "",
    }


def normalize_project_metadata(project_id: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    base = default_project_metadata(project_id)
    if not isinstance(metadata, dict):
        return base
    for key in ("title", "originalTitle", "author", "artist", "status", "year", "description", "coverFile", "coverSourceUrl", "updatedAt"):
        value = metadata.get(key)
        if value is not None:
            base[key] = str(value).strip()
    for key in ("genres", "tags"):
        value = metadata.get(key)
        if isinstance(value, list):
            base[key] = [str(item).strip() for item in value if str(item).strip()][:12]
    source = metadata.get("source")
    base["source"] = source if isinstance(source, dict) else {}
    if not base["title"]:
        base["title"] = project_id
    return base


def load_project_metadata(project_id: str) -> dict[str, Any]:
    path = project_metadata_file(project_id)
    if not path.exists() or path.stat().st_size == 0:
        return default_project_metadata(project_id)
    try:
        return normalize_project_metadata(project_id, json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        corrupt = path.with_suffix(f".corrupt-{uuid4().hex}.json")
        shutil.copy2(path, corrupt)
        return default_project_metadata(project_id)


def save_project_metadata(project_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    path = project_metadata_file(project_id)
    existing = load_project_metadata(project_id)
    merged = normalize_project_metadata(project_id, {**existing, **(metadata or {})})
    merged["updatedAt"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".{uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return merged


def project_cover_path(project_id: str) -> Path | None:
    root = project_path(project_id)
    metadata = load_project_metadata(project_id)
    cover_file = metadata.get("coverFile")
    if cover_file:
        try:
            candidate = root / safe_path_part(cover_file, "kapak görseli")
        except ValueError:
            candidate = None
        if candidate and candidate.suffix.lower() in ALLOWED_EXTENSIONS and candidate.exists():
            return candidate
    for candidate in sorted(root.glob(f"{PROJECT_COVER_STEM}.*"), key=lambda p: natural_key(p.name)):
        if candidate.suffix.lower() in ALLOWED_EXTENSIONS and candidate.exists():
            return candidate
    return None


def save_project_cover(project_id: str, content: bytes, source_url: str = "", content_type: str = "") -> dict[str, Any]:
    if not content:
        raise ValueError("Kapak görseli boş.")
    root = project_path(project_id)
    suffix = cover_suffix_from_source(source_url, content_type)
    filename = f"{PROJECT_COVER_STEM}{suffix}"
    for old_cover in root.glob(f"{PROJECT_COVER_STEM}.*"):
        if old_cover.name != filename and old_cover.is_file():
            old_cover.unlink()
    path = root / filename
    path.write_bytes(content)
    metadata = load_project_metadata(project_id)
    metadata["coverFile"] = filename
    metadata["coverSourceUrl"] = source_url
    return save_project_metadata(project_id, metadata)


def cover_suffix_from_source(source_url: str, content_type: str) -> str:
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if normalized_type == "image/png":
        return ".png"
    if normalized_type == "image/webp":
        return ".webp"
    suffix = Path(source_url.split("?", 1)[0]).suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return suffix
    return ".jpg"


def list_projects() -> list[dict[str, Any]]:
    ensure_dirs()
    records = []
    for item in sorted(PROJECTS_DIR.iterdir(), key=lambda p: natural_key(p.name)):
        if not item.is_dir():
            continue
        metadata = load_project_metadata(item.name)
        episode_count = sum(1 for child in item.iterdir() if child.is_dir())
        records.append(
            {
                "id": item.name,
                "name": metadata.get("title") or item.name,
                "folderName": item.name,
                "episodeCount": episode_count,
                "hasCover": project_cover_path(item.name) is not None,
                "metadata": metadata,
            }
        )
    return records


def list_episodes(project_id: str) -> list[dict[str, str]]:
    root = project_path(project_id)
    if not root.exists():
        return []
    return [
        {"id": item.name, "name": item.name}
        for item in sorted(root.iterdir(), key=lambda p: natural_key(p.name))
        if item.is_dir()
    ]


def page_records(project_id: str, episode_id: str) -> list[dict[str, Any]]:
    episode = ensure_episode_layout(project_id, episode_id)
    edited = episode / EDITED_DIR_NAME
    hidden_pages = hidden_page_ids_from_episode(episode)
    records = []
    for file in sorted(edited.iterdir(), key=lambda p: natural_key(p.name)):
        if file.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if file.name in hidden_pages:
            continue
        width = height = 0
        try:
            with Image.open(file) as image:
                width, height = image.size
        except Exception:
            pass
        records.append({"id": file.name, "name": file.name, "width": width, "height": height})
    return records


def state_file(project_id: str, episode_id: str) -> Path:
    return episode_path(project_id, episode_id) / DATA_DIR_NAME / "state.json"


def load_state(project_id: str, episode_id: str) -> dict[str, Any]:
    ensure_episode_layout(project_id, episode_id)
    path = state_file(project_id, episode_id)
    with STATE_LOCK:
        if not path.exists() or path.stat().st_size == 0:
            return default_state()
        try:
            return normalize_state(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            corrupt = path.with_suffix(f".corrupt-{uuid4().hex}.json")
            shutil.copy2(path, corrupt)
            return default_state()


def save_state(project_id: str, episode_id: str, state: dict[str, Any]) -> dict[str, Any]:
    path = state_file(project_id, episode_id)
    with STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".{uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    return state


def add_box(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    state = load_state(project_id, episode_id)
    page_id = payload["pageId"]
    box = asdict(TextBox(id=uuid4().hex, pageId=page_id, bbox=payload["bbox"], order=1))
    if isinstance(payload.get("style"), dict):
        box["style"].update(payload["style"])
    if isinstance(payload.get("corners"), dict):
        box["corners"] = normalized_box_corners({"bbox": payload["bbox"], "corners": payload["corners"]})
    state["boxes"].append(box)
    renumber_boxes(state)
    save_state(project_id, episode_id, state)
    return next(item for item in state["boxes"] if item["id"] == box["id"])


def update_box(project_id: str, episode_id: str, box_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    state = load_state(project_id, episode_id)
    for box in state["boxes"]:
        if box["id"] == box_id:
            for key, value in patch.items():
                if key in {"bbox", "corners", "sourceText", "translatedText", "status", "style", "placement", "order"}:
                    box[key] = normalized_box_corners({"bbox": box.get("bbox", {}), "corners": value}) if key == "corners" else value
            renumber_boxes(state)
            save_state(project_id, episode_id, state)
            return box
    return None


def apply_text_style(project_id: str, episode_id: str, patch: dict[str, Any], box_ids: list[str] | None = None) -> list[dict[str, Any]]:
    state = load_state(project_id, episode_id)
    allowed = set(TextStyle.__dataclass_fields__)
    style_patch = {key: value for key, value in patch.items() if key in allowed}
    ids = set(box_ids) if box_ids else None
    updated = []
    if not style_patch:
        return updated
    for box in state["boxes"]:
        if ids is not None and box["id"] not in ids:
            continue
        style = box.setdefault("style", default_text_style())
        style.update(style_patch)
        updated.append(box)
    if updated:
        save_state(project_id, episode_id, state)
    return updated


def delete_box(project_id: str, episode_id: str, box_id: str) -> bool:
    state = load_state(project_id, episode_id)
    next_boxes = [box for box in state["boxes"] if box["id"] != box_id]
    if len(next_boxes) == len(state["boxes"]):
        return False
    state["boxes"] = next_boxes
    renumber_boxes(state)
    save_state(project_id, episode_id, state)
    return True


def image_path(project_id: str, episode_id: str, page_id: str) -> Path:
    return ensure_episode_layout(project_id, episode_id) / EDITED_DIR_NAME / safe_image_name(page_id)


def original_image_path(project_id: str, episode_id: str, page_id: str) -> Path:
    episode = ensure_episode_layout(project_id, episode_id)
    return find_original_dir(episode) / safe_image_name(page_id)


def backup_image(project_id: str, episode_id: str, page_id: str) -> Path:
    source = image_path(project_id, episode_id, page_id)
    backup_dir = episode_path(project_id, episode_id) / BACKUP_DIR_NAME / page_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{uuid4().hex}{source.suffix}"
    shutil.copy2(source, target)
    return target


def manual_mask_dir(project_id: str, episode_id: str) -> Path:
    directory = episode_path(project_id, episode_id) / DATA_DIR_NAME / MANUAL_MASK_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def history_dir(project_id: str, episode_id: str) -> Path:
    directory = episode_path(project_id, episode_id) / DATA_DIR_NAME / HISTORY_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def history_entry_dir(project_id: str, episode_id: str, entry_id: str) -> Path:
    directory = history_dir(project_id, episode_id) / safe_path_part(entry_id, "geçmiş kaydı")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def manual_mask_path(project_id: str, episode_id: str, mask: dict[str, Any] | str) -> Path:
    if isinstance(mask, dict):
        filename = mask.get("maskFile") or f"{mask.get('id', '')}.png"
    else:
        filename = f"{mask}.png"
    return manual_mask_dir(project_id, episode_id) / safe_image_name(filename)


def history_image_path(project_id: str, episode_id: str, entry: dict[str, Any], key: str) -> Path:
    entry_id = safe_path_part(entry.get("id", ""), "geçmiş kaydı")
    filename = safe_image_name(entry.get(key, ""))
    return history_entry_dir(project_id, episode_id, entry_id) / filename


def clamped_box(bbox: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    left = max(0, math.floor(float(bbox.get("x", 0))))
    top = max(0, math.floor(float(bbox.get("y", 0))))
    right = min(width, math.ceil(float(bbox.get("x", 0)) + float(bbox.get("w", 0))))
    bottom = min(height, math.ceil(float(bbox.get("y", 0)) + float(bbox.get("h", 0))))
    if right <= left or bottom <= top:
        raise ValueError("Seçili kutunun alanı geçersiz.")
    return left, top, right, bottom


def save_image_like_source(image: Image.Image, path: Path) -> None:
    if path.suffix.lower() in {".jpg", ".jpeg", ".webp"}:
        image.convert("RGB").save(path, quality=95)
    else:
        image.save(path)


def page_merge_segments(
    state: dict[str, Any],
    page_id: str,
    size: tuple[int, int],
    offset_y: int = 0,
) -> list[dict[str, Any]]:
    width, height = size
    segments = (state.get("pageMerges") or {}).get(page_id)
    if not isinstance(segments, list) or not segments:
        return [
            {
                "sourcePageId": page_id,
                "x": 0.0,
                "y": float(offset_y),
                "width": float(width),
                "height": float(height),
            }
        ]

    normalized = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        normalized.append(
            {
                "sourcePageId": str(segment.get("sourcePageId") or segment.get("pageId") or page_id),
                "x": float(segment.get("x", 0)),
                "y": float(segment.get("y", 0)) + float(offset_y),
                "width": float(segment.get("width", width)),
                "height": float(segment.get("height", height)),
            }
        )
    return normalized or page_merge_segments({}, page_id, size, offset_y)


def original_canvas_for_page(
    project_id: str,
    episode_id: str,
    page_id: str,
    target_size: tuple[int, int],
    state: dict[str, Any] | None = None,
) -> Image.Image:
    state = state or load_state(project_id, episode_id)
    segments = (state.get("pageMerges") or {}).get(page_id)
    if not isinstance(segments, list) or not segments:
        source_path = original_image_path(project_id, episode_id, page_id)
        if not source_path.exists():
            raise FileNotFoundError(f"Orijinal görsel bulunamadı: {source_path.name}")
        with Image.open(source_path) as original_image:
            return original_image.convert("RGBA")

    canvas = Image.new("RGBA", target_size, (255, 255, 255, 255))
    for segment in page_merge_segments(state, page_id, target_size):
        source_id = segment["sourcePageId"]
        source_path = original_image_path(project_id, episode_id, source_id)
        if not source_path.exists():
            raise FileNotFoundError(f"Orijinal görsel bulunamadı: {source_path.name}")
        paste_x = int(round(float(segment.get("x", 0))))
        paste_y = int(round(float(segment.get("y", 0))))
        with Image.open(source_path) as source_image:
            source = source_image.convert("RGBA")
            left = max(0, paste_x)
            top = max(0, paste_y)
            right = min(canvas.width, paste_x + source.width)
            bottom = min(canvas.height, paste_y + source.height)
            if right > left and bottom > top:
                crop = source.crop((left - paste_x, top - paste_y, right - paste_x, bottom - paste_y))
                canvas.alpha_composite(crop, (left, top))
    return canvas


def shift_record_bbox_y(record: dict[str, Any], delta_y: int) -> None:
    bbox = record.get("bbox")
    if not isinstance(bbox, dict):
        return
    bbox["y"] = float(bbox.get("y", 0)) + float(delta_y)


def expand_mask_canvas(path: Path, size: tuple[int, int], offset_y: int) -> None:
    if not path.exists():
        return
    with Image.open(path) as mask_image:
        mask = mask_image.convert("L")
    expanded = Image.new("L", size, 0)
    expanded.paste(mask, (0, offset_y))
    expanded.save(path)


def merge_page_with_next(project_id: str, episode_id: str, page_id: str) -> dict[str, Any]:
    pages = page_records(project_id, episode_id)
    page_index = next((index for index, page in enumerate(pages) if page["id"] == page_id), -1)
    if page_index < 0:
        raise FileNotFoundError(f"Sayfa bulunamadı: {page_id}")
    if page_index >= len(pages) - 1:
        raise ValueError("Bu sayfadan sonra birleştirilecek sayfa yok.")

    next_page_id = pages[page_index + 1]["id"]
    target_path = image_path(project_id, episode_id, page_id)
    next_path = image_path(project_id, episode_id, next_page_id)
    if not target_path.exists():
        raise FileNotFoundError(f"Sayfa görseli bulunamadı: {target_path.name}")
    if not next_path.exists():
        raise FileNotFoundError(f"Sonraki sayfa görseli bulunamadı: {next_path.name}")

    with Image.open(target_path) as target_image, Image.open(next_path) as next_image:
        target = target_image.convert("RGBA")
        next_item = next_image.convert("RGBA")
        target_size = target.size
        next_size = next_item.size
        merged_size = (max(target.width, next_item.width), target.height + next_item.height)
        merged = Image.new("RGBA", merged_size, (255, 255, 255, 255))
        merged.alpha_composite(target, (0, 0))
        merged.alpha_composite(next_item, (0, target.height))

    state = load_state(project_id, episode_id)
    backup_image(project_id, episode_id, page_id)
    backup_image(project_id, episode_id, next_page_id)
    save_image_like_source(merged, target_path)
    next_path.unlink()

    hidden_pages = state.setdefault("hiddenPages", [])
    if next_page_id not in hidden_pages:
        hidden_pages.append(next_page_id)
    page_merges = state.setdefault("pageMerges", {})
    page_merges[page_id] = [
        *page_merge_segments(state, page_id, target_size, 0),
        *page_merge_segments(state, next_page_id, next_size, target_size[1]),
    ]
    page_merges.pop(next_page_id, None)

    for box in state.setdefault("boxes", []):
        if box.get("pageId") == next_page_id:
            box["pageId"] = page_id
            shift_record_bbox_y(box, target_size[1])

    for mask in state.setdefault("manualMasks", []):
        mask_page_id = mask.get("pageId")
        if mask_page_id == page_id:
            expand_mask_canvas(manual_mask_path(project_id, episode_id, mask), merged_size, 0)
        elif mask_page_id == next_page_id:
            expand_mask_canvas(manual_mask_path(project_id, episode_id, mask), merged_size, target_size[1])
            mask["pageId"] = page_id
            shift_record_bbox_y(mask, target_size[1])

    state["undo"] = []
    state["redo"] = []
    renumber_boxes(state)
    save_state(project_id, episode_id, state)
    return {
        "pageId": page_id,
        "mergedPageId": next_page_id,
        "width": merged_size[0],
        "height": merged_size[1],
        "message": f"{page_id} ile {next_page_id} birleştirildi.",
    }


def begin_image_history(
    project_id: str,
    episode_id: str,
    page_id: str,
    kind: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = image_path(project_id, episode_id, page_id)
    entry_id = uuid4().hex
    before_file = f"before{source.suffix.lower()}"
    after_file = f"after{source.suffix.lower()}"
    entry = {
        "id": entry_id,
        "pageId": page_id,
        "type": kind,
        "beforeFile": before_file,
        "afterFile": after_file,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if meta:
        entry["meta"] = meta
    shutil.copy2(source, history_image_path(project_id, episode_id, entry, "beforeFile"))
    return entry


def record_image_history(
    project_id: str,
    episode_id: str,
    entry: dict[str, Any],
    mask_file: str | None = None,
) -> dict[str, Any]:
    source = image_path(project_id, episode_id, entry["pageId"])
    if mask_file:
        entry["maskFile"] = mask_file
    entry["completedAt"] = datetime.now(timezone.utc).isoformat()
    shutil.copy2(source, history_image_path(project_id, episode_id, entry, "afterFile"))
    state = load_state(project_id, episode_id)
    state.setdefault("undo", []).append(entry)
    state["redo"] = []
    save_state(project_id, episode_id, state)
    return entry


def undo_image_history(project_id: str, episode_id: str) -> dict[str, Any] | None:
    state = load_state(project_id, episode_id)
    stack = state.setdefault("undo", [])
    if not stack:
        return None
    entry = stack.pop()
    source = history_image_path(project_id, episode_id, entry, "beforeFile")
    if not source.exists():
        raise FileNotFoundError(f"Geri alma görseli bulunamadı: {source.name}")
    shutil.copy2(source, image_path(project_id, episode_id, entry["pageId"]))
    entry["undoneAt"] = datetime.now(timezone.utc).isoformat()
    apply_history_state_effect(state, entry, "undo")
    state.setdefault("redo", []).append(entry)
    save_state(project_id, episode_id, state)
    return entry


def redo_image_history(project_id: str, episode_id: str) -> dict[str, Any] | None:
    state = load_state(project_id, episode_id)
    stack = state.setdefault("redo", [])
    if not stack:
        return None
    entry = stack.pop()
    source = history_image_path(project_id, episode_id, entry, "afterFile")
    if not source.exists():
        raise FileNotFoundError(f"Yineleme görseli bulunamadı: {source.name}")
    shutil.copy2(source, image_path(project_id, episode_id, entry["pageId"]))
    entry["redoneAt"] = datetime.now(timezone.utc).isoformat()
    apply_history_state_effect(state, entry, "redo")
    state.setdefault("undo", []).append(entry)
    save_state(project_id, episode_id, state)
    return entry


def apply_history_state_effect(state: dict[str, Any], entry: dict[str, Any], action: str) -> None:
    mask_id = (entry.get("meta") or {}).get("maskId")
    if not mask_id:
        return
    manual_mask = next((item for item in state.setdefault("manualMasks", []) if item.get("id") == mask_id), None)
    if manual_mask is None:
        return
    if entry.get("type") == "manual-inpaint":
        manual_mask["status"] = "undone" if action == "undo" else "cleaned"
    if entry.get("type") == "manual-mask-restore":
        manual_mask["status"] = "cleaned" if action == "undo" else "restored"


def add_manual_mask(project_id: str, episode_id: str, page_id: str, mask_payload: str, bbox: dict[str, Any] | None) -> dict[str, Any]:
    record = save_brush_mask(project_id, episode_id, page_id, mask_payload, bbox)
    state = load_state(project_id, episode_id)
    state.setdefault("manualMasks", []).append(record)
    save_state(project_id, episode_id, state)
    return record


def save_brush_mask(project_id: str, episode_id: str, page_id: str, mask_payload: str, bbox: dict[str, Any] | None) -> dict[str, Any]:
    edited_path = image_path(project_id, episode_id, page_id)
    with Image.open(edited_path) as image:
        page_size = image.size
    uploaded_mask = decode_mask_image(mask_payload)
    full_mask, normalized_bbox = compose_full_page_mask(uploaded_mask, bbox, page_size)
    if full_mask.getbbox() is None:
        raise ValueError("Fırça maskesi boş.")

    mask_id = uuid4().hex
    mask_file = f"{mask_id}.png"
    path = manual_mask_path(project_id, episode_id, mask_file[:-4])
    full_mask.save(path)
    return asdict(ManualMask(id=mask_id, pageId=page_id, bbox=normalized_bbox, maskFile=mask_file))


def decode_mask_image(mask_payload: str) -> Image.Image:
    if not isinstance(mask_payload, str) or not mask_payload.strip():
        raise ValueError("Fırça maskesi alınamadı.")
    payload = mask_payload.strip()
    if payload.startswith("data:"):
        if "," not in payload:
            raise ValueError("Fırça maskesi formatı geçersiz.")
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Fırça maskesi çözümlenemedi.") from error
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.mode in {"RGBA", "LA"}:
                mask = image.getchannel("A").copy()
            else:
                mask = image.convert("L")
    except Exception as error:
        raise ValueError("Fırça maskesi geçerli bir PNG değil.") from error
    return mask.point(lambda pixel: 255 if pixel > 0 else 0)


def compose_full_page_mask(
    uploaded_mask: Image.Image,
    bbox: dict[str, Any] | None,
    page_size: tuple[int, int],
) -> tuple[Image.Image, dict[str, float]]:
    width, height = page_size
    if bbox:
        left, top, right, bottom = clamped_box(bbox, width, height)
        target_size = (right - left, bottom - top)
        if uploaded_mask.size != target_size:
            uploaded_mask = uploaded_mask.resize(target_size, NEAREST_RESAMPLE)
        full_mask = Image.new("L", page_size, 0)
        full_mask.paste(uploaded_mask, (left, top))
        return full_mask, {"x": float(left), "y": float(top), "w": float(target_size[0]), "h": float(target_size[1])}

    if uploaded_mask.size != page_size:
        raise ValueError("Fırça maskesi sayfa boyutuyla eşleşmiyor.")
    return uploaded_mask, {"x": 0.0, "y": 0.0, "w": float(width), "h": float(height)}


def update_manual_mask(project_id: str, episode_id: str, mask_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    state = load_state(project_id, episode_id)
    for mask in state.setdefault("manualMasks", []):
        if mask.get("id") == mask_id:
            for key, value in patch.items():
                if key in {"status", "bbox", "restoredAt", "updatedAt"}:
                    mask[key] = value
            save_state(project_id, episode_id, state)
            return mask
    return None


def manual_mask_overlay(project_id: str, episode_id: str, mask_id: str) -> BytesIO | None:
    state = load_state(project_id, episode_id)
    mask_record = next((item for item in state.setdefault("manualMasks", []) if item.get("id") == mask_id), None)
    if mask_record is None:
        return None
    path = manual_mask_path(project_id, episode_id, mask_record)
    if not path.exists():
        raise FileNotFoundError(f"Fırça maskesi bulunamadı: {path.name}")
    with Image.open(path) as mask_image:
        mask = mask_image.convert("L")
        alpha = mask.point(lambda pixel: 118 if pixel > 0 else 0)
        overlay = Image.new("RGBA", mask.size, (231, 189, 84, 0))
        overlay.putalpha(alpha)
        buffer = BytesIO()
        overlay.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer


def paste_original_with_mask(project_id: str, episode_id: str, page_id: str, mask_path: Path) -> None:
    edited_path = image_path(project_id, episode_id, page_id)
    if not mask_path.exists():
        raise FileNotFoundError(f"Fırça maskesi bulunamadı: {mask_path.name}")

    state = load_state(project_id, episode_id)
    with Image.open(edited_path) as edited_image, Image.open(mask_path) as mask_image:
        edited = edited_image.convert("RGBA")
        original = original_canvas_for_page(project_id, episode_id, page_id, edited.size, state)
        mask = mask_image.convert("L")
        width = min(edited.width, original.width, mask.width)
        height = min(edited.height, original.height, mask.height)
        if width <= 0 or height <= 0:
            raise ValueError("Fırça maskesi alanı geçersiz.")
        edited.paste(original.crop((0, 0, width, height)), (0, 0), mask.crop((0, 0, width, height)))
        save_image_like_source(edited, edited_path)


def restore_brush_from_original(
    project_id: str,
    episode_id: str,
    page_id: str,
    mask_payload: str,
    bbox: dict[str, Any] | None,
) -> dict[str, Any]:
    mask_record = save_brush_mask(project_id, episode_id, page_id, mask_payload, bbox)
    paste_original_with_mask(project_id, episode_id, page_id, manual_mask_path(project_id, episode_id, mask_record))
    mask_record["status"] = "restored"
    return mask_record


def restore_box_from_original(project_id: str, episode_id: str, box_id: str) -> dict[str, Any] | None:
    state = load_state(project_id, episode_id)
    box = next((item for item in state["boxes"] if item["id"] == box_id), None)
    if box is None:
        return None

    edited_path = image_path(project_id, episode_id, box["pageId"])

    history = begin_image_history(project_id, episode_id, box["pageId"], "box-restore", {"boxId": box_id})
    backup_image(project_id, episode_id, box["pageId"])
    with Image.open(edited_path) as edited_image:
        edited = edited_image.convert("RGBA")
        original = original_canvas_for_page(project_id, episode_id, box["pageId"], edited.size, state)
        left, top, right, bottom = clamped_box(box["bbox"], min(edited.width, original.width), min(edited.height, original.height))
        restored_region = original.crop((left, top, right, bottom))
        if has_custom_box_corners(box):
            mask = polygon_mask_for_box(box, edited.size).crop((left, top, right, bottom))
            edited.paste(restored_region, (left, top), mask)
        else:
            edited.paste(restored_region, (left, top))
        save_image_like_source(edited, edited_path)

    box["status"] = "restored"
    save_state(project_id, episode_id, state)
    record_image_history(project_id, episode_id, history)
    return box


def restore_manual_mask_from_original(project_id: str, episode_id: str, mask_id: str) -> dict[str, Any] | None:
    state = load_state(project_id, episode_id)
    mask_record = next((item for item in state.setdefault("manualMasks", []) if item.get("id") == mask_id), None)
    if mask_record is None:
        return None

    page_id = mask_record["pageId"]
    stored_mask_path = manual_mask_path(project_id, episode_id, mask_record)
    if not stored_mask_path.exists():
        raise FileNotFoundError(f"Fırça maskesi bulunamadı: {stored_mask_path.name}")

    history = begin_image_history(project_id, episode_id, page_id, "manual-mask-restore", {"maskId": mask_id})
    backup_image(project_id, episode_id, page_id)
    paste_original_with_mask(project_id, episode_id, page_id, stored_mask_path)

    mask_record["status"] = "restored"
    mask_record["restoredAt"] = datetime.now(timezone.utc).isoformat()
    save_state(project_id, episode_id, state)
    record_image_history(project_id, episode_id, history, mask_record.get("maskFile"))
    return mask_record


def render_texts(project_id: str, episode_id: str, page_id: str, boxes: list[dict[str, Any]]) -> None:
    path = image_path(project_id, episode_id, page_id)
    backup_image(project_id, episode_id, page_id)
    with Image.open(path).convert("RGBA") as image:
        for box in boxes:
            if box.get("status") != "placed":
                continue
            text = box.get("translatedText") or box.get("sourceText") or ""
            if not text.strip():
                continue
            bbox = box["bbox"]
            style = box.get("style") or {}
            text_layer = transform_text_layer(draw_text_layer(text, bbox, style, allow_overflow=not has_custom_box_corners(box)), style)
            warped = warp_text_layer(text_layer, box)
            if warped:
                paste_rgba(image, warped[0], warped[1], warped[2])
            else:
                paste_x = int(float(bbox["x"]) + float(bbox["w"]) / 2 - text_layer.width / 2)
                paste_y = int(float(bbox["y"]) + float(bbox["h"]) / 2 - text_layer.height / 2)
                paste_rgba(image, text_layer, paste_x, paste_y)
        image.convert("RGB").save(path)


def draw_text_layer(text: str, bbox: dict[str, Any], style: dict[str, Any], allow_overflow: bool = True) -> Image.Image:
    width = max(1, int(float(bbox["w"])))
    height = max(1, int(float(bbox["h"])))
    size = positive_int(style.get("fontSize"), 6, 240, 28)
    stroke_width = int(style.get("strokeWidth", 1))
    font = load_font(size, bool(style.get("bold")), style.get("fontFamily", "noto-sans-black"))
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    lines = layout_text_lines(measure, text, font, max(1, width - 12))
    line_height = int(size * float(style.get("lineHeight", 1.1)))
    total_height = line_height * len(lines)
    max_line_width = max((measure.textlength(line, font=font) if line else 0 for line in lines), default=0)
    padding_x = padding_y = 0
    if allow_overflow:
        stroke_padding = max(8, stroke_width * 4)
        padding_x = int(max(size + stroke_padding, (max_line_width - width) / 2 + stroke_padding, 24))
        padding_y = int(max(size + stroke_padding, (total_height - height) / 2 + stroke_padding, 24))
    layer = Image.new("RGBA", (width + padding_x * 2, height + padding_y * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    y = int(padding_y + (height - total_height) / 2)
    for line in lines:
        line_width = draw.textlength(line, font=font) if line else 0
        align = style.get("align", "center")
        if align == "left":
            x = padding_x + 6
        elif align == "right":
            x = padding_x + width - line_width - 6
        else:
            x = int(padding_x + (width - line_width) / 2)
        if line:
            draw.text(
                (x, y),
                line,
                font=font,
                fill=style.get("color", "#111111"),
                stroke_width=stroke_width,
                stroke_fill=style.get("strokeColor", "#ffffff"),
            )
        y += line_height
    return layer


def transform_text_layer(layer: Image.Image, style: dict[str, Any]) -> Image.Image:
    resample = Image.Resampling.BICUBIC
    scale_x = clamp_float(style.get("scaleX", 1), 0.35, 3.0, 1.0)
    if abs(scale_x - 1) > 0.01:
        layer = layer.resize((max(1, int(layer.width * scale_x)), layer.height), resample)

    skew_x = clamp_float(style.get("skewX", 0), -55, 55, 0)
    if abs(skew_x) > 0.1:
        skew = math.tan(math.radians(skew_x))
        x_shift = abs(skew) * layer.height
        output_width = max(1, int(layer.width + x_shift))
        offset = x_shift if skew > 0 else 0
        layer = layer.transform((output_width, layer.height), Image.Transform.AFFINE, (1, -skew, offset, 0, 1, 0), resample)

    perspective_x = clamp_float(style.get("perspectiveX", 0), -80, 80, 0)
    perspective_y = clamp_float(style.get("perspectiveY", 0), -80, 80, 0)
    if abs(perspective_x) > 0.1 or abs(perspective_y) > 0.1:
        layer = perspective_layer(layer, perspective_x, perspective_y)

    rotation = clamp_float(style.get("rotation", 0), -180, 180, 0)
    if abs(rotation) > 0.1:
        layer = layer.rotate(rotation, expand=True, resample=resample)
    return layer


def perspective_layer(layer: Image.Image, perspective_x: float, perspective_y: float) -> Image.Image:
    try:
        import numpy as np
    except Exception:
        return layer

    width, height = layer.size
    destination = perspective_destination(width, height, perspective_x, perspective_y)
    source = [(0, 0), (width, 0), (width, height), (0, height)]
    coefficients = perspective_coefficients(destination, source, np)
    return layer.transform((width, height), Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC)


def warp_text_layer(layer: Image.Image, box: dict[str, Any]) -> tuple[Image.Image, int, int] | None:
    if not has_custom_box_corners(box):
        return None
    try:
        import numpy as np
    except Exception:
        return None

    destination = absolute_box_points(box)
    min_x = math.floor(min(point[0] for point in destination))
    min_y = math.floor(min(point[1] for point in destination))
    max_x = math.ceil(max(point[0] for point in destination))
    max_y = math.ceil(max(point[1] for point in destination))
    output_width = max(1, max_x - min_x)
    output_height = max(1, max_y - min_y)
    local_destination = [(x - min_x, y - min_y) for x, y in destination]
    source = [(0, 0), (layer.width, 0), (layer.width, layer.height), (0, layer.height)]
    try:
        coefficients = perspective_coefficients(local_destination, source, np)
    except Exception:
        return None
    warped = layer.transform((output_width, output_height), Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC)
    return warped, min_x, min_y


def has_custom_box_corners(box: dict[str, Any]) -> bool:
    corners = normalized_box_corners(box)
    defaults = default_warp_corners()
    for key in defaults:
        if abs(corners[key]["x"] - defaults[key]["x"]) > 0.001:
            return True
        if abs(corners[key]["y"] - defaults[key]["y"]) > 0.001:
            return True
    return False


def absolute_box_points(box: dict[str, Any]) -> list[tuple[float, float]]:
    bbox = box.get("bbox") or {}
    corners = normalized_box_corners(box)
    x = float(bbox.get("x", 0))
    y = float(bbox.get("y", 0))
    width = float(bbox.get("w", 1))
    height = float(bbox.get("h", 1))
    return [
        (x + corners["tl"]["x"] * width, y + corners["tl"]["y"] * height),
        (x + corners["tr"]["x"] * width, y + corners["tr"]["y"] * height),
        (x + corners["br"]["x"] * width, y + corners["br"]["y"] * height),
        (x + corners["bl"]["x"] * width, y + corners["bl"]["y"] * height),
    ]


def normalized_box_corners(box: dict[str, Any]) -> dict[str, dict[str, float]]:
    incoming = box.get("corners")
    if not isinstance(incoming, dict) and isinstance(box.get("style"), dict):
        incoming = box["style"].get("warpCorners")
    defaults = default_warp_corners()
    if not isinstance(incoming, dict):
        return defaults
    corners = default_warp_corners()
    for key in corners:
        value = incoming.get(key)
        if isinstance(value, dict):
            corners[key] = {
                "x": clamp_float(value.get("x"), -1.0, 2.0, defaults[key]["x"]),
                "y": clamp_float(value.get("y"), -1.0, 2.0, defaults[key]["y"]),
            }
    return corners


def polygon_mask_for_box(box: dict[str, Any], size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(absolute_box_points(box), fill=255)
    return mask


def perspective_destination(width: int, height: int, perspective_x: float, perspective_y: float) -> list[tuple[float, float]]:
    top_left = [0.0, 0.0]
    top_right = [float(width), 0.0]
    bottom_right = [float(width), float(height)]
    bottom_left = [0.0, float(height)]

    x_amount = min(height * 0.42, abs(perspective_x) / 100 * height * 0.72)
    if perspective_x > 0:
        top_right[1] += x_amount
        bottom_right[1] -= x_amount
    elif perspective_x < 0:
        top_left[1] += x_amount
        bottom_left[1] -= x_amount

    y_amount = min(width * 0.42, abs(perspective_y) / 100 * width * 0.72)
    if perspective_y > 0:
        bottom_left[0] += y_amount
        bottom_right[0] -= y_amount
    elif perspective_y < 0:
        top_left[0] += y_amount
        top_right[0] -= y_amount

    return [tuple(top_left), tuple(top_right), tuple(bottom_right), tuple(bottom_left)]


def perspective_coefficients(destination: list[tuple[float, float]], source: list[tuple[float, float]], np: Any) -> list[float]:
    matrix = []
    vector = []
    for (x, y), (u, v) in zip(destination, source):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        vector.extend([u, v])
    return np.linalg.solve(np.array(matrix, dtype=float), np.array(vector, dtype=float)).tolist()


def paste_rgba(base: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    left = max(0, x)
    top = max(0, y)
    right = min(base.width, x + layer.width)
    bottom = min(base.height, y + layer.height)
    if right <= left or bottom <= top:
        return
    crop = layer.crop((left - x, top - y, right - x, bottom - y))
    base.alpha_composite(crop, (left, top))


def clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(parsed, minimum), maximum)


def positive_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed) or parsed <= 0:
        return fallback
    return int(min(max(parsed, minimum), maximum))


def load_font(size: int, bold: bool = False, font_family: str = "noto-sans-black") -> ImageFont.FreeTypeFont:
    selected = font_path(font_family, bold)
    if selected:
        return ImageFont.truetype(str(selected), size)
    candidates = [
        "/usr/share/fonts/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    raise RuntimeError("Unicode destekli yazı tipi bulunamadı. Noto Sans veya DejaVu Sans kurulmalı.")


def layout_text_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    lines: list[str] = []
    for manual_line in normalized.split("\n"):
        lines.extend(wrap_text_line(draw, manual_line, font, max_width))
    return lines


def wrap_text_line(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if text == "":
        return [""]
    if draw.textlength(text, font=font) <= max_width:
        return [text]

    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines or [text]

import json
import math
import re
import shutil
from threading import RLock
from dataclasses import asdict, dataclass, field
from pathlib import Path
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


def ensure_episode_layout(project_id: str, episode_id: str) -> Path:
    episode = episode_path(project_id, episode_id)
    original = find_original_dir(episode)
    edited = episode / EDITED_DIR_NAME
    for dirname in (DATA_DIR_NAME, BACKUP_DIR_NAME, OUTPUT_DIR_NAME):
        (episode / dirname).mkdir(parents=True, exist_ok=True)
    edited.mkdir(parents=True, exist_ok=True)
    original.mkdir(parents=True, exist_ok=True)
    for image in sorted(original.iterdir(), key=lambda p: natural_key(p.name)):
        if image.suffix.lower() in ALLOWED_EXTENSIONS:
            target = edited / image.name
            if not target.exists():
                shutil.copy2(image, target)
    return episode


def list_projects() -> list[dict[str, str]]:
    ensure_dirs()
    return [
        {"id": item.name, "name": item.name}
        for item in sorted(PROJECTS_DIR.iterdir(), key=lambda p: natural_key(p.name))
        if item.is_dir()
    ]


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
    records = []
    for file in sorted(edited.iterdir(), key=lambda p: natural_key(p.name)):
        if file.suffix.lower() not in ALLOWED_EXTENSIONS:
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
            return {"boxes": [], "undo": [], "redo": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt = path.with_suffix(f".corrupt-{uuid4().hex}.json")
            shutil.copy2(path, corrupt)
            return {"boxes": [], "undo": [], "redo": []}


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


def restore_box_from_original(project_id: str, episode_id: str, box_id: str) -> dict[str, Any] | None:
    state = load_state(project_id, episode_id)
    box = next((item for item in state["boxes"] if item["id"] == box_id), None)
    if box is None:
        return None

    edited_path = image_path(project_id, episode_id, box["pageId"])
    source_path = original_image_path(project_id, episode_id, box["pageId"])
    if not source_path.exists():
        raise FileNotFoundError(f"Orijinal görsel bulunamadı: {source_path.name}")

    backup_image(project_id, episode_id, box["pageId"])
    with Image.open(edited_path) as edited_image, Image.open(source_path) as original_image:
        edited = edited_image.convert("RGBA")
        original = original_image.convert("RGBA")
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
    return box


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
            text_layer = transform_text_layer(draw_text_layer(text, bbox, style), style)
            warped = warp_text_layer(text_layer, box)
            if warped:
                paste_rgba(image, warped[0], warped[1], warped[2])
            else:
                paste_x = int(float(bbox["x"]) + float(bbox["w"]) / 2 - text_layer.width / 2)
                paste_y = int(float(bbox["y"]) + float(bbox["h"]) / 2 - text_layer.height / 2)
                paste_rgba(image, text_layer, paste_x, paste_y)
        image.convert("RGB").save(path)


def draw_text_layer(text: str, bbox: dict[str, Any], style: dict[str, Any]) -> Image.Image:
    width = max(1, int(float(bbox["w"])))
    height = max(1, int(float(bbox["h"])))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    size = int(style.get("fontSize", 28))
    stroke_width = int(style.get("strokeWidth", 1))
    font = load_font(size, bool(style.get("bold")), style.get("fontFamily", "noto-sans-black"))
    lines = layout_text_lines(draw, text, font, max(1, width - 12))
    line_height = int(size * float(style.get("lineHeight", 1.1)))
    total_height = line_height * len(lines)
    y = int((height - total_height) / 2)
    for line in lines:
        line_width = draw.textlength(line, font=font) if line else 0
        align = style.get("align", "center")
        if align == "left":
            x = 6
        elif align == "right":
            x = width - line_width - 6
        else:
            x = int((width - line_width) / 2)
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

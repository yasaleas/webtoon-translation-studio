from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image, ImageDraw

from ..settings import active_gemini_api_key, ai_bool, ai_value

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_use_onednn", "0")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")


MODEL_REGISTRY = {
    "detector": "RT-DETR V2",
    "ocr": "PaddleOCR-VL 1.5",
    "translator": "Gemini",
    "inpaint": "IOPaint",
}

_OCR_PIPELINE: Any = None
_RTDETR_MODEL: Any = None
_RTDETR_PROCESSOR: Any = None
_RTDETR_ONNX: Any = None


def detect_text_regions(page: dict[str, Any], image_file: str | Path | None = None) -> list[dict[str, float]]:
    if image_file:
        model_boxes = detect_with_rtdetr(Path(image_file))
        if model_boxes:
            return model_boxes

    if image_file:
        detected = detect_light_text_regions(Path(image_file))
        if detected:
            return detected

    width = page.get("width") or 900
    height = page.get("height") or 1400
    return [
        {"x": width * 0.18, "y": height * 0.06, "w": width * 0.54, "h": height * 0.12},
    ]


def detect_with_rtdetr(image_file: Path) -> list[dict[str, float]]:
    model_id = str(ai_value("rtdetrModelId", "RTDETR_MODEL_ID", "ogkalu/comic-text-and-bubble-detector")).strip()
    if not model_id:
        return []

    global _RTDETR_MODEL, _RTDETR_PROCESSOR
    try:
        onnx_boxes = detect_with_rtdetr_onnx(image_file, model_id)
        if onnx_boxes:
            return onnx_boxes

        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        if _RTDETR_MODEL is None or _RTDETR_PROCESSOR is None:
            _RTDETR_PROCESSOR = AutoImageProcessor.from_pretrained(model_id)
            _RTDETR_MODEL = AutoModelForObjectDetection.from_pretrained(model_id)
            _RTDETR_MODEL.eval()

        image = Image.open(image_file).convert("RGB")
        inputs = _RTDETR_PROCESSOR(images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = _RTDETR_MODEL(**inputs)
        target_sizes = torch.tensor([image.size[::-1]])
        results = _RTDETR_PROCESSOR.post_process_object_detection(
            outputs,
            target_sizes=target_sizes,
            threshold=float(ai_value("rtdetrThreshold", "RTDETR_THRESHOLD", 0.45)),
        )[0]

        allowed_labels = {
            item.strip().lower()
            for item in str(ai_value("rtdetrTextLabels", "RTDETR_TEXT_LABELS", "text_bubble,text_free")).split(",")
            if item.strip()
        }
        boxes = []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            label_name = _RTDETR_MODEL.config.id2label.get(int(label), str(int(label))).lower()
            if allowed_labels and label_name not in allowed_labels:
                continue
            x1, y1, x2, y2 = [float(value) for value in box.tolist()]
            boxes.append({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "score": float(score)})
        return sorted(boxes, key=lambda item: (item["y"], item["x"]))
    except Exception as error:
        if ai_bool("strictMode", "AI_STRICT"):
            raise RuntimeError(f"RT-DETR V2 çalıştırılamadı: {error}") from error
        return []


def detect_with_rtdetr_onnx(image_file: Path, model_id: str) -> list[dict[str, float]]:
    global _RTDETR_ONNX, _RTDETR_PROCESSOR
    try:
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoImageProcessor

        if _RTDETR_PROCESSOR is None:
            _RTDETR_PROCESSOR = AutoImageProcessor.from_pretrained(model_id)
        if _RTDETR_ONNX is None:
            onnx_file = hf_hub_download(model_id, "detector.onnx")
            _RTDETR_ONNX = ort.InferenceSession(onnx_file, providers=["CPUExecutionProvider"])

        image = Image.open(image_file).convert("RGB")
        inputs = _RTDETR_PROCESSOR(images=image, return_tensors="np")
        labels, boxes, scores = _RTDETR_ONNX.run(
            None,
            {
                "images": inputs["pixel_values"].astype("float32"),
                "orig_target_sizes": np.array([[image.width, image.height]], dtype=np.int64),
            },
        )
        id2label = {0: "bubble", 1: "text_bubble", 2: "text_free"}
        allowed_labels = {
            item.strip().lower()
            for item in str(ai_value("rtdetrTextLabels", "RTDETR_TEXT_LABELS", "text_bubble,text_free")).split(",")
            if item.strip()
        }
        threshold = float(ai_value("rtdetrThreshold", "RTDETR_THRESHOLD", 0.55))
        candidates = []
        for label, box, score in zip(labels[0], boxes[0], scores[0]):
            label_name = id2label.get(int(label), str(int(label)))
            if label_name not in allowed_labels or float(score) < threshold:
                continue
            x1, y1, x2, y2 = [float(value) for value in box]
            candidates.append(
                {
                    "x": max(0, x1),
                    "y": max(0, y1),
                    "w": min(float(image.width), x2) - max(0, x1),
                    "h": min(float(image.height), y2) - max(0, y1),
                    "score": float(score),
                    "label": label_name,
                }
            )
        return sorted(non_max_suppression(candidates), key=lambda item: (item["y"], item["x"]))
    except Exception:
        return []


def non_max_suppression(boxes: list[dict[str, float]]) -> list[dict[str, float]]:
    kept: list[dict[str, float]] = []
    for box in sorted(boxes, key=lambda item: item.get("score", 0), reverse=True):
        if box["w"] <= 3 or box["h"] <= 3:
            continue
        if any(overlap_ratio(existing, box) > 0.45 for existing in kept):
            continue
        kept.append(box)
    return kept


def detect_light_text_regions(image_file: Path) -> list[dict[str, float]]:
    with Image.open(image_file).convert("RGB") as source:
        original_width, original_height = source.size
        scale = min(1.0, 520 / max(original_width, original_height))
        image = source.resize((int(original_width * scale), int(original_height * scale)))

    width, height = image.size
    pixels = image.load()
    visited = bytearray(width * height)
    boxes: list[dict[str, float]] = []

    for y in range(height):
        for x in range(width):
            index = y * width + x
            if visited[index] or not is_balloon_pixel(pixels[x, y]):
                visited[index] = 1
                continue

            min_x = max_x = x
            min_y = max_y = y
            area = 0
            queue = deque([(x, y)])
            visited[index] = 1

            while queue:
                cx, cy = queue.popleft()
                area += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)

                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    next_index = ny * width + nx
                    if visited[next_index]:
                        continue
                    visited[next_index] = 1
                    if is_balloon_pixel(pixels[nx, ny]):
                        queue.append((nx, ny))

            candidate_width = max_x - min_x + 1
            candidate_height = max_y - min_y + 1
            if not is_valid_balloon_candidate(area, candidate_width, candidate_height, width, height):
                continue
            if not has_text_like_marks(pixels, min_x, min_y, max_x, max_y):
                continue

            padding = max(2, int(8 * scale))
            boxes.append(
                {
                    "x": max(0, (min_x - padding) / scale),
                    "y": max(0, (min_y - padding) / scale),
                    "w": min(original_width, candidate_width / scale + (padding * 2) / scale),
                    "h": min(original_height, candidate_height / scale + (padding * 2) / scale),
                }
            )

    return sorted(merge_close_boxes(boxes), key=lambda box: (box["y"], box["x"]))


def is_balloon_pixel(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    brightness = (red + green + blue) / 3
    contrast = max(pixel) - min(pixel)
    return brightness >= 188 and contrast <= 62


def is_valid_balloon_candidate(area: int, width: int, height: int, image_width: int, image_height: int) -> bool:
    if width < 12 or height < 8:
        return False
    if area < 80:
        return False
    if width > image_width * 0.72:
        return False
    if height > image_height * 0.06:
        return False
    if area > image_width * image_height * 0.28:
        return False
    fill_ratio = area / (width * height)
    aspect = width / max(1, height)
    return fill_ratio >= 0.22 and 0.28 <= aspect <= 5.8


def has_text_like_marks(pixels: Any, min_x: int, min_y: int, max_x: int, max_y: int) -> bool:
    dark = 0
    total = 0
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            red, green, blue = pixels[x, y]
            total += 1
            if (red + green + blue) / 3 < 55:
                dark += 1
    density = dark / total if total else 0
    return 0.12 <= density <= 0.62


def merge_close_boxes(boxes: list[dict[str, float]]) -> list[dict[str, float]]:
    merged: list[dict[str, float]] = []
    for box in boxes:
        target = next((item for item in merged if overlap_ratio(item, box) > 0.18), None)
        if not target:
            merged.append(box)
            continue
        x1 = min(target["x"], box["x"])
        y1 = min(target["y"], box["y"])
        x2 = max(target["x"] + target["w"], box["x"] + box["w"])
        y2 = max(target["y"] + target["h"], box["y"] + box["h"])
        target.update({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1})
    return merged


def overlap_ratio(first: dict[str, float], second: dict[str, float]) -> float:
    x1 = max(first["x"], second["x"])
    y1 = max(first["y"], second["y"])
    x2 = min(first["x"] + first["w"], second["x"] + second["w"])
    y2 = min(first["y"] + first["h"], second["y"] + second["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    smaller = min(first["w"] * first["h"], second["w"] * second["h"])
    return intersection / smaller if smaller else 0


def run_ocr(image_file: str | Path, box: dict[str, Any]) -> str:
    crop_file = crop_box(Path(image_file), box)
    try:
        text = run_paddleocr_vl(crop_file)
        return text or detect_punctuation_text(crop_file)
    finally:
        crop_file.unlink(missing_ok=True)


def crop_box(image_file: Path, box: dict[str, Any]) -> Path:
    bbox = box["bbox"]
    with Image.open(image_file).convert("RGB") as image:
        left = max(0, int(bbox["x"]))
        top = max(0, int(bbox["y"]))
        right = min(image.width, int(bbox["x"] + bbox["w"]))
        bottom = min(image.height, int(bbox["y"] + bbox["h"]))
        if has_custom_box_corners(box):
            crop = perspective_crop_box(image, box)
        else:
            crop = image.crop((left, top, right, bottom))
        target = image_file.parent / f".ocr_{image_file.stem}_{left}_{top}.png"
        crop.save(target)
        return target


def perspective_crop_box(image: Image.Image, box: dict[str, Any]) -> Image.Image:
    width = max(1, int(float(box["bbox"].get("w", 1))))
    height = max(1, int(float(box["bbox"].get("h", 1))))
    source = absolute_box_points(box)
    destination = [(0, 0), (width, 0), (width, height), (0, height)]
    try:
        coefficients = perspective_coefficients(destination, source)
    except Exception:
        left = max(0, int(box["bbox"]["x"]))
        top = max(0, int(box["bbox"]["y"]))
        right = min(image.width, int(box["bbox"]["x"] + box["bbox"]["w"]))
        bottom = min(image.height, int(box["bbox"]["y"] + box["bbox"]["h"]))
        crop = image.crop((left, top, right, bottom))
        mask = polygon_mask_for_box(box, image.size).crop((left, top, right, bottom))
        background = Image.new("RGB", crop.size, "white")
        background.paste(crop, (0, 0), mask)
        return background
    return image.transform((width, height), Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC)


def run_paddleocr_vl(image_file: Path) -> str:
    global _OCR_PIPELINE
    try:
        if _OCR_PIPELINE is None:
            try:
                from paddleocr import PaddleOCRVL

                _OCR_PIPELINE = (
                    "vl",
                    PaddleOCRVL(
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_layout_detection=False,
                    ),
                )
            except Exception:
                from paddleocr import PaddleOCR

                _OCR_PIPELINE = (
                    "ocr",
                    PaddleOCR(
                        lang=str(ai_value("ocrLanguage", "OCR_LANG", "en")),
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    ),
                )

        kind, pipeline = _OCR_PIPELINE
        if kind == "vl":
            output = pipeline.predict(str(image_file))
            return extract_paddle_text(output)

        output = pipeline.predict(str(image_file))
        return extract_paddle_text(output)
    except Exception as error:
        raise RuntimeError(f"PaddleOCR-VL 1.5 OCR çalıştırılamadı: {error}") from error


def extract_paddle_text(output: Any) -> str:
    fragments: list[str] = []

    def walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            if value.strip():
                fragments.append(value.strip())
            return
        if isinstance(value, dict):
            for key in ("text", "rec_text", "rec_texts", "text_content", "markdown"):
                if key in value:
                    walk(value[key])
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
            return
        for attr in ("json", "res", "text", "markdown"):
            if hasattr(value, attr):
                try:
                    walk(getattr(value, attr))
                except Exception:
                    pass

    walk(output)
    return "\n".join(dict.fromkeys(fragments)).strip()


def detect_punctuation_text(image_file: Path) -> str:
    with Image.open(image_file).convert("L") as image:
        width, height = image.size
        pixels = image.load()
        visited = bytearray(width * height)
        components: list[tuple[int, int, int, int, int]] = []

        for y in range(height):
            for x in range(width):
                index = y * width + x
                if visited[index] or pixels[x, y] > 95:
                    visited[index] = 1
                    continue
                stack = [(x, y)]
                visited[index] = 1
                min_x = max_x = x
                min_y = max_y = y
                area = 0
                while stack:
                    cx, cy = stack.pop()
                    area += 1
                    min_x = min(min_x, cx)
                    max_x = max(max_x, cx)
                    min_y = min(min_y, cy)
                    max_y = max(max_y, cy)
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if nx < 0 or ny < 0 or nx >= width or ny >= height:
                            continue
                        next_index = ny * width + nx
                        if visited[next_index]:
                            continue
                        visited[next_index] = 1
                        if pixels[nx, ny] <= 95:
                            stack.append((nx, ny))
                comp_w = max_x - min_x + 1
                comp_h = max_y - min_y + 1
                fill = area / max(1, comp_w * comp_h)
                if 8 <= area <= 900 and 3 <= comp_w <= 40 and 3 <= comp_h <= 40 and 0.25 <= fill <= 1:
                    components.append((min_x, min_y, max_x, max_y, area))

    if not 1 <= len(components) <= 6:
        return ""
    components.sort(key=lambda item: (item[1], item[0]))
    heights = [item[3] - item[1] + 1 for item in components]
    centers_y = [(item[1] + item[3]) / 2 for item in components]
    if max(centers_y) - min(centers_y) > max(18, max(heights) * 2.5):
        return ""
    return "." * len(components)


def translate_texts(texts: list[str], target_language: str) -> list[str]:
    if not texts:
        return []
    api_key = active_gemini_api_key()
    if not api_key:
        raise RuntimeError("Gemini çalışması için Ayarlar menüsünden aktif API key seçilmeli.")
    try:
        model = str(ai_value("geminiModel", "GEMINI_MODEL", "gemini-2.5-flash"))
        return translate_batch_resilient(api_key, model, texts, target_language)
    except Exception as error:
        raise RuntimeError(f"Gemini çeviri çalıştırılamadı: {error}") from error


def split_translation_batches(texts: list[str]) -> list[list[str]]:
    max_items = int(clamp_float(ai_value("geminiBatchSize", "GEMINI_BATCH_SIZE", 8), 1, 24, 8))
    max_chars = int(clamp_float(ai_value("geminiBatchChars", "GEMINI_BATCH_CHARS", 2200), 400, 12000, 2200))
    batches: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for text in texts:
        text_chars = len(text or "")
        if current and (len(current) >= max_items or current_chars + text_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(text)
        current_chars += text_chars
    if current:
        batches.append(current)
    return batches


def translate_batch_resilient(api_key: str, model: str, texts: list[str], target_language: str) -> list[str]:
    try:
        return translate_text_batch(api_key, model, texts, target_language)
    except Exception as error:
        if len(texts) > 1 and should_split_translation_error(error):
            midpoint = max(1, len(texts) // 2)
            return [
                *translate_batch_resilient(api_key, model, texts[:midpoint], target_language),
                *translate_batch_resilient(api_key, model, texts[midpoint:], target_language),
            ]
        raise


def translate_text_batch(api_key: str, model: str, texts: list[str], target_language: str) -> list[str]:
    if len(texts) == 1:
        translated = clean_translation_text(
            gemini_generate(
                api_key,
                model,
                (
                    f"Translate this webtoon text to {target_language}. "
                    "Return only the translated text, no numbering, no notes. "
                    "Keep it concise and natural for comic lettering.\n\n"
                    f"{texts[0]}"
                ),
            )
        )
        return [translated or texts[0]]

    prompt = (
        f"Translate this JSON array of webtoon text into {target_language}. "
        "Return only a valid JSON array of strings. "
        "The returned array length must match the input array length exactly. "
        "Keep each item natural, concise, and suitable for comic lettering. "
        "If the target language is Turkish, prefer natural uppercase Turkish lettering.\n\n"
        f"{json.dumps(texts, ensure_ascii=False)}"
    )
    raw_text = gemini_generate(api_key, model, prompt, json_mode=True)
    translations = parse_translation_response(raw_text, len(texts))
    if translations is None:
        translations = retry_translation_text_batch(api_key, model, texts, target_language)
    return translations


def retry_translation_text_batch(api_key: str, model: str, texts: list[str], target_language: str) -> list[str]:
    prompt = (
        f"Translate every item in this numbered list into {target_language}. "
        "Return only one numbered line per input item, keep the same numbers, and do not add notes. "
        "Keep each translation natural, concise, and suitable for webtoon lettering.\n\n"
        + "\n".join(f"{index + 1}. {text}" for index, text in enumerate(texts))
    )
    raw_text = gemini_generate(api_key, model, prompt)
    translations = parse_translation_response(raw_text, len(texts))
    if translations is None:
        raise RuntimeError("Gemini beklenen sayıda çeviri döndürmedi.")
    return translations


def should_split_translation_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("timed out", "timeout", "read timed out", "502", "503", "504", "temporarily unavailable"))


def gemini_generate(api_key: str, model: str, prompt: str, json_mode: bool = False) -> str:
    import requests

    timeout = int(clamp_float(ai_value("geminiTimeout", "GEMINI_TIMEOUT", 60), 15, 180, 60))
    body: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json=body,
        timeout=timeout,
    )
    if response.status_code >= 400 and json_mode:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=timeout,
        )
    response.raise_for_status()
    payload = response.json()
    return payload["candidates"][0]["content"]["parts"][0]["text"]


def translate_texts_one_by_one(api_key: str, model: str, texts: list[str], target_language: str) -> list[str]:
    translations = []
    for text in texts:
        prompt = (
            f"Translate this webtoon text to {target_language}. "
            "Return only the translated text, no numbering, no notes. "
            "Keep it concise and natural for comic lettering.\n\n"
            f"{text}"
        )
        translated = clean_translation_text(gemini_generate(api_key, model, prompt))
        if not translated:
            translated = text
        translations.append(translated)
    return translations


def parse_translation_response(raw_text: str, expected_count: int) -> list[str] | None:
    cleaned = strip_code_fence(raw_text).strip()
    parsed = parse_translation_json(cleaned)
    if parsed and len(parsed) == expected_count:
        return parsed

    numbered = parse_numbered_translations(cleaned, expected_count)
    if numbered and len(numbered) == expected_count:
        return numbered

    if expected_count == 1 and cleaned:
        return [clean_translation_text(cleaned)]
    return None


def parse_translation_json(text: str) -> list[str] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    if isinstance(payload, list):
        return [clean_translation_text(str(item)) for item in payload]
    if isinstance(payload, dict):
        for key in ("translations", "items", "result", "results"):
            if isinstance(payload.get(key), list):
                return [clean_translation_text(str(item)) for item in payload[key]]
        numeric_items = []
        for key, value in payload.items():
            if str(key).isdigit():
                numeric_items.append((int(key), clean_translation_text(str(value))))
        if numeric_items:
            return [value for _, value in sorted(numeric_items)]
    return None


def parse_numbered_translations(text: str, expected_count: int) -> list[str] | None:
    values: dict[int, list[str]] = {}
    current_index: int | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(\d+)\s*[\.\):\-\]]\s*(.*)$", line)
        if match:
            current_index = int(match.group(1))
            values.setdefault(current_index, [])
            if match.group(2).strip():
                values[current_index].append(match.group(2).strip())
            continue
        if current_index is not None:
            values[current_index].append(line)

    if not values:
        return None
    translations = []
    for index in range(1, expected_count + 1):
        parts = values.get(index)
        if not parts:
            return None
        translations.append(clean_translation_text(" ".join(parts)))
    return translations


def strip_code_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    return fence.group(1) if fence else text


def clean_translation_text(text: str) -> str:
    text = strip_number_prefix(strip_code_fence(text))
    text = text.strip().strip('"').strip()
    return re.sub(r"\s+", " ", text)


def strip_number_prefix(line: str) -> str:
    return re.sub(r"^\s*\d+\s*[\.\):\-]\s*", "", line).strip()


def inpaint_region(image_file: str | Path, box: dict[str, Any]) -> dict[str, str]:
    image_file = Path(image_file)
    iopaint = shutil.which("iopaint")
    if not iopaint:
        local_iopaint = Path(".venv-ai/bin/iopaint")
        if local_iopaint.exists():
            iopaint = str(local_iopaint)
    if not iopaint:
        raise RuntimeError("IOPaint bulunamadı. `.venv-ai/bin/python -m pip install iopaint` çalışmalı.")

    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        input_dir = temp / "image"
        mask_dir = temp / "mask"
        output_dir = temp / "output"
        input_dir.mkdir()
        mask_dir.mkdir()
        output_dir.mkdir()
        input_file = input_dir / "page.png"
        mask_file = mask_dir / "page.png"
        with Image.open(image_file) as image:
            image.convert("RGB").save(input_file, format="PNG")
        create_mask(image_file, mask_file, box)
        command = [
            iopaint,
            "run",
            "--model",
            str(ai_value("inpaintModel", "IOPAINT_MODEL", "lama")),
            "--device",
            str(ai_value("aiDevice", "AI_DEVICE", "cpu")),
            "--image",
            str(input_dir),
            "--mask",
            str(mask_dir),
            "--output",
            str(output_dir),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout or "IOPaint başarısız oldu.")
        produced = next(output_dir.glob("*"), None)
        if not produced:
            raise RuntimeError("IOPaint çıktı üretmedi.")
        save_inpaint_output(produced, image_file)
    return {"status": "cleaned", "engine": MODEL_REGISTRY["inpaint"]}


def save_inpaint_output(produced: Path, image_file: Path) -> None:
    suffix = image_file.suffix.lower()
    with Image.open(produced) as image:
        if suffix == ".webp":
            image.convert("RGB").save(image_file, format="WEBP", quality=95, method=6)
        elif suffix in {".jpg", ".jpeg"}:
            image.convert("RGB").save(image_file, format="JPEG", quality=95)
        else:
            image.save(image_file, format="PNG")


def create_mask(image_file: Path, mask_file: Path, box: dict[str, Any]) -> None:
    with Image.open(image_file) as image:
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        pad = int(ai_value("inpaintPadding", "INPAINT_PADDING", 8))
        if has_custom_box_corners(box):
            draw.polygon(expanded_box_points(box, pad), fill=255)
        else:
            bbox = box["bbox"] if "bbox" in box else box
            left = max(0, int(bbox["x"]) - pad)
            top = max(0, int(bbox["y"]) - pad)
            right = min(image.width, int(bbox["x"] + bbox["w"]) + pad)
            bottom = min(image.height, int(bbox["y"] + bbox["h"]) + pad)
            draw.rectangle((left, top, right, bottom), fill=255)
        mask.save(mask_file)


def default_box_corners() -> dict[str, dict[str, float]]:
    return {
        "tl": {"x": 0.0, "y": 0.0},
        "tr": {"x": 1.0, "y": 0.0},
        "br": {"x": 1.0, "y": 1.0},
        "bl": {"x": 0.0, "y": 1.0},
    }


def normalized_box_corners(box: dict[str, Any]) -> dict[str, dict[str, float]]:
    incoming = box.get("corners")
    if not isinstance(incoming, dict) and isinstance(box.get("style"), dict):
        incoming = box["style"].get("warpCorners")
    defaults = default_box_corners()
    if not isinstance(incoming, dict):
        return defaults
    corners = default_box_corners()
    for key in corners:
        value = incoming.get(key)
        if isinstance(value, dict):
            corners[key] = {
                "x": clamp_float(value.get("x"), -1.0, 2.0, defaults[key]["x"]),
                "y": clamp_float(value.get("y"), -1.0, 2.0, defaults[key]["y"]),
            }
    return corners


def has_custom_box_corners(box: dict[str, Any]) -> bool:
    corners = normalized_box_corners(box)
    defaults = default_box_corners()
    return any(
        abs(corners[key]["x"] - defaults[key]["x"]) > 0.001 or abs(corners[key]["y"] - defaults[key]["y"]) > 0.001
        for key in defaults
    )


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


def expanded_box_points(box: dict[str, Any], padding: int) -> list[tuple[float, float]]:
    points = absolute_box_points(box)
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    expanded = []
    for x, y in points:
        dx = x - center_x
        dy = y - center_y
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        expanded.append((x + padding * dx / length, y + padding * dy / length))
    return expanded


def polygon_mask_for_box(box: dict[str, Any], size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(absolute_box_points(box), fill=255)
    return mask


def perspective_coefficients(destination: list[tuple[float, float]], source: list[tuple[float, float]]) -> list[float]:
    import numpy as np

    matrix = []
    vector = []
    for (x, y), (u, v) in zip(destination, source):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        vector.extend([u, v])
    return np.linalg.solve(np.array(matrix, dtype=float), np.array(vector, dtype=float)).tolist()


def clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(parsed, minimum), maximum)

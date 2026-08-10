from __future__ import annotations

import json
import math
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
    "detector": "RT-DETR V2 / YOLO / Manga text segmentation",
    "ocr": "PaddleOCR-VL 1.5",
    "translator": "Gemini",
    "inpaint": "IOPaint",
}
NEAREST_RESAMPLE = getattr(Image, "Resampling", Image).NEAREST
DEFAULT_DETECTOR_MODEL = "ogkalu/comic-text-and-bubble-detector"
MANGA_TEXT_SEGMENTATION_2025_MODEL = "a-b-c-x-y-z/Manga-Text-Segmentation-2025"
ULTRALYTICS_DETECTOR_FILES = {
    "ogkalu/comic-text-segmenter-yolov8m": "comic-text-segmenter.pt",
    "huyvux3005/manga109-segmentation-bubble": "best.pt",
}
DETECTOR_MODEL_TITLES = {
    DEFAULT_DETECTOR_MODEL: "RT-DETR V2",
    "ogkalu/comic-text-segmenter-yolov8m": "YOLOv8m text segmenter",
    "huyvux3005/manga109-segmentation-bubble": "YOLO11 bubble segmentation",
    MANGA_TEXT_SEGMENTATION_2025_MODEL: "Manga Text Segmentation 2025",
}
DETECTOR_MODEL_DEFAULTS = {
    DEFAULT_DETECTOR_MODEL: {"threshold": 0.55, "labels": "text_bubble,text_free", "output": "bubble,text_bubble,text_free"},
    "ogkalu/comic-text-segmenter-yolov8m": {"threshold": 0.55, "labels": "text_comic", "output": "text_comic"},
    "huyvux3005/manga109-segmentation-bubble": {"threshold": 0.55, "labels": "balloon", "output": "balloon"},
    MANGA_TEXT_SEGMENTATION_2025_MODEL: {"threshold": 0.55, "labels": "text", "output": "text-mask"},
}

_OCR_PIPELINE: Any = None
_OCR_GEOMETRY_PIPELINE: Any = None
_RTDETR_MODEL: Any = None
_RTDETR_PROCESSOR: Any = None
_RTDETR_ONNX: Any = None
_RTDETR_MODEL_ID: str = ""
_RTDETR_ONNX_MODEL_ID: str = ""
_YOLO_MODELS: dict[tuple[str, str], Any] = {}
_MANGA_TEXT_SEGMENTATION_CACHE: dict[tuple[str, str], Any] = {}


def detect_text_regions(page: dict[str, Any], image_file: str | Path | None = None) -> list[dict[str, float]]:
    return detect_text_regions_with_info(page, image_file)["boxes"]


def detect_text_regions_with_info(page: dict[str, Any], image_file: str | Path | None = None) -> dict[str, Any]:
    selected = current_detector_model_info()
    if image_file:
        model_boxes = detect_with_configured_model(Path(image_file))
        if model_boxes:
            return {
                "boxes": model_boxes,
                "detector": {**selected, "activeTitle": selected["title"], "source": "model"},
            }

    if image_file and ai_bool("detectorFallbackEnabled", "DETECTOR_FALLBACK_ENABLED", False):
        detected = detect_light_text_regions(Path(image_file))
        if detected:
            return {
                "boxes": detected,
                "detector": {
                    **selected,
                    "activeTitle": "Yerel hafif balon algılayıcı",
                    "source": "fallback",
                },
            }

    return {
        "boxes": [],
        "detector": {
            **selected,
            "activeTitle": selected["title"],
            "source": "none",
        },
    }


def current_detector_model_info() -> dict[str, str]:
    return detector_model_info(str(ai_value("rtdetrModelId", "RTDETR_MODEL_ID", DEFAULT_DETECTOR_MODEL)).strip())


def detector_model_info(model_id: str) -> dict[str, str]:
    normalized = normalize_detector_model_id(model_id or DEFAULT_DETECTOR_MODEL)
    if normalized == MANGA_TEXT_SEGMENTATION_2025_MODEL:
        family = "manga-text-segmentation"
    elif is_ultralytics_detector(normalized):
        family = "ultralytics"
    else:
        family = "rtdetr"
    return {
        "id": normalized,
        "title": DETECTOR_MODEL_TITLES.get(normalized, normalized),
        "family": family,
        "activeTitle": DETECTOR_MODEL_TITLES.get(normalized, normalized),
        "source": "model",
        "output": str(DETECTOR_MODEL_DEFAULTS.get(normalized, {}).get("output", "")),
    }


def detect_with_configured_model(image_file: Path) -> list[dict[str, float]]:
    model_id = normalize_detector_model_id(str(ai_value("rtdetrModelId", "RTDETR_MODEL_ID", DEFAULT_DETECTOR_MODEL)).strip())
    if not model_id:
        return []
    try:
        if model_id == MANGA_TEXT_SEGMENTATION_2025_MODEL:
            return detect_with_manga_text_segmentation_2025(image_file, model_id)
        if is_ultralytics_detector(model_id):
            return detect_with_ultralytics(image_file, model_id)
        return detect_with_rtdetr(image_file, model_id)
    except Exception as error:
        if ai_bool("strictMode", "AI_STRICT"):
            title = DETECTOR_MODEL_TITLES.get(model_id, model_id)
            raise RuntimeError(f"{title} çalıştırılamadı: {error}") from error
        return []


def normalize_detector_model_id(model_id: str) -> str:
    aliases = {
        "Manga-Text-Segmentation-2025": MANGA_TEXT_SEGMENTATION_2025_MODEL,
        "manga-text-segmentation-2025": MANGA_TEXT_SEGMENTATION_2025_MODEL,
        "comic-text-segmenter-yolov8m": "ogkalu/comic-text-segmenter-yolov8m",
        "manga109-segmentation-bubble": "huyvux3005/manga109-segmentation-bubble",
    }
    return aliases.get(model_id, model_id)


def is_ultralytics_detector(model_id: str) -> bool:
    lowered = model_id.lower()
    return model_id in ULTRALYTICS_DETECTOR_FILES or "yolo" in lowered or lowered.endswith(".pt")


def detect_with_rtdetr(image_file: Path, model_id: str | None = None) -> list[dict[str, float]]:
    model_id = model_id or str(ai_value("rtdetrModelId", "RTDETR_MODEL_ID", DEFAULT_DETECTOR_MODEL)).strip()
    model_id = normalize_detector_model_id(model_id)
    if not model_id:
        return []

    global _RTDETR_MODEL, _RTDETR_PROCESSOR, _RTDETR_MODEL_ID
    try:
        onnx_boxes = detect_with_rtdetr_onnx(image_file, model_id)
        if onnx_boxes:
            return onnx_boxes

        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        if _RTDETR_MODEL is None or _RTDETR_PROCESSOR is None or _RTDETR_MODEL_ID != model_id:
            _RTDETR_PROCESSOR = AutoImageProcessor.from_pretrained(model_id)
            _RTDETR_MODEL = AutoModelForObjectDetection.from_pretrained(model_id)
            _RTDETR_MODEL.eval()
            _RTDETR_MODEL_ID = model_id

        image = Image.open(image_file).convert("RGB")
        inputs = _RTDETR_PROCESSOR(images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = _RTDETR_MODEL(**inputs)
        target_sizes = torch.tensor([image.size[::-1]])
        results = _RTDETR_PROCESSOR.post_process_object_detection(
            outputs,
            target_sizes=target_sizes,
            threshold=detector_threshold(model_id),
        )[0]

        allowed_labels = detector_allowed_labels(model_id)
        boxes = []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            label_name = _RTDETR_MODEL.config.id2label.get(int(label), str(int(label))).lower()
            if allowed_labels and not detector_label_allowed(label_name, allowed_labels):
                continue
            x1, y1, x2, y2 = [float(value) for value in box.tolist()]
            boxes.append(clamp_detection_box({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "score": float(score)}, image.size))
        return sorted(boxes, key=lambda item: (item["y"], item["x"]))
    except Exception as error:
        if ai_bool("strictMode", "AI_STRICT"):
            raise RuntimeError(f"RT-DETR V2 çalıştırılamadı: {error}") from error
        return []


def detect_with_rtdetr_onnx(image_file: Path, model_id: str) -> list[dict[str, float]]:
    global _RTDETR_ONNX, _RTDETR_PROCESSOR, _RTDETR_ONNX_MODEL_ID
    try:
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoImageProcessor

        if _RTDETR_PROCESSOR is None or _RTDETR_ONNX_MODEL_ID != model_id:
            _RTDETR_PROCESSOR = AutoImageProcessor.from_pretrained(model_id)
        if _RTDETR_ONNX is None or _RTDETR_ONNX_MODEL_ID != model_id:
            onnx_file = hf_hub_download(model_id, "detector.onnx")
            _RTDETR_ONNX = ort.InferenceSession(onnx_file, providers=["CPUExecutionProvider"])
            _RTDETR_ONNX_MODEL_ID = model_id

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
        allowed_labels = detector_allowed_labels(model_id)
        threshold = detector_threshold(model_id)
        candidates = []
        for label, box, score in zip(labels[0], boxes[0], scores[0]):
            label_name = id2label.get(int(label), str(int(label)))
            if not detector_label_allowed(label_name, allowed_labels) or float(score) < threshold:
                continue
            x1, y1, x2, y2 = [float(value) for value in box]
            candidates.append(clamp_detection_box({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "score": float(score), "label": label_name}, image.size))
        return sorted(non_max_suppression(candidates), key=lambda item: (item["y"], item["x"]))
    except Exception:
        return []


def detect_with_ultralytics(image_file: Path, model_id: str) -> list[dict[str, float]]:
    from ultralytics import YOLO

    model_path = resolve_ultralytics_model_path(model_id)
    device = ultralytics_device()
    cache_key = (model_id, str(model_path))
    model = _YOLO_MODELS.get(cache_key)
    if model is None:
        model = YOLO(str(model_path))
        _YOLO_MODELS[cache_key] = model

    threshold = detector_threshold(model_id)
    kwargs = {"source": str(image_file), "conf": threshold, "verbose": False}
    if device:
        kwargs["device"] = device
    results = model.predict(**kwargs)
    with Image.open(image_file) as image:
        image_size = image.size

    allowed_labels = detector_allowed_labels(model_id)
    boxes: list[dict[str, float]] = []
    for result in results:
        result_boxes = getattr(result, "boxes", None)
        if result_boxes is None:
            continue
        xyxy = result_boxes.xyxy.cpu().numpy().tolist() if getattr(result_boxes, "xyxy", None) is not None else []
        scores = result_boxes.conf.cpu().numpy().tolist() if getattr(result_boxes, "conf", None) is not None else [1.0] * len(xyxy)
        classes = result_boxes.cls.cpu().numpy().tolist() if getattr(result_boxes, "cls", None) is not None else [0] * len(xyxy)
        names = getattr(result, "names", None) or getattr(model, "names", {}) or {}
        polygons = yolo_mask_polygons(result)
        for index, box in enumerate(xyxy):
            label_name = str(names.get(int(classes[index]), int(classes[index]))).lower() if isinstance(names, dict) else str(classes[index])
            if allowed_labels and not detector_label_allowed(label_name, allowed_labels):
                continue
            if index < len(polygons) and len(polygons[index]) > 0:
                candidate = bbox_from_polygon(polygons[index])
            else:
                x1, y1, x2, y2 = [float(value) for value in box]
                candidate = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
            candidate["score"] = float(scores[index]) if index < len(scores) else 1.0
            candidate["label"] = label_name
            boxes.append(clamp_detection_box(candidate, image_size))
    return sorted(non_max_suppression(boxes), key=lambda item: (item["y"], item["x"]))


def resolve_ultralytics_model_path(model_id: str) -> str | Path:
    local_path = Path(model_id).expanduser()
    if local_path.exists():
        return local_path
    filename = ULTRALYTICS_DETECTOR_FILES.get(model_id)
    if filename:
        from huggingface_hub import hf_hub_download

        return hf_hub_download(model_id, filename)
    return model_id


def ultralytics_device() -> str | int:
    device = str(ai_value("aiDevice", "AI_DEVICE", "cpu")).strip().lower()
    if device in {"cuda", "gpu"}:
        return 0
    return device or "cpu"


def yolo_mask_polygons(result: Any) -> list[Any]:
    masks = getattr(result, "masks", None)
    polygons = getattr(masks, "xy", None)
    return list(polygons or [])


def bbox_from_polygon(points: Any) -> dict[str, float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def detect_with_manga_text_segmentation_2025(image_file: Path, model_id: str) -> list[dict[str, float]]:
    import gc
    import cv2
    import numpy as np
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import segmentation_models_pytorch as smp
    from huggingface_hub import hf_hub_download

    device_name = str(ai_value("aiDevice", "AI_DEVICE", "cpu")).strip().lower()
    device = "cuda" if device_name == "cuda" and torch.cuda.is_available() else "cpu"
    cache_key = (model_id, device)
    model = _MANGA_TEXT_SEGMENTATION_CACHE.get(cache_key)
    if model is None:
        model_path = hf_hub_download(model_id, "model.pth")
        model = smp.UnetPlusPlus(
            encoder_name="tu-efficientnetv2_rw_m",
            encoder_weights=None,
            in_channels=3,
            classes=1,
            activation=None,
            decoder_attention_type="scse",
        )
        convert_batchnorm_to_groupnorm(model.decoder, nn)
        state_dict = torch.load(model_path, map_location=device)
        model.load_state_dict(state_dict)
        model.to(device)
        model.eval()
        _MANGA_TEXT_SEGMENTATION_CACHE[cache_key] = model

    with Image.open(image_file).convert("RGB") as source:
        image_size = source.size
        orig_w, orig_h = image_size
        max_dim = 2048
        if max(orig_w, orig_h) > max_dim:
            scale = max_dim / float(max(orig_w, orig_h))
            scaled_w = max(32, int(round(orig_w * scale)))
            scaled_h = max(32, int(round(orig_h * scale)))
            scaled_image = source.resize((scaled_w, scaled_h), Image.Resampling.BILINEAR)
            image = np.array(scaled_image)
        else:
            image = np.array(source)

    height, width = image.shape[:2]
    normalized = image.astype("float32") / 255.0
    normalized = (normalized - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    tensor = torch.from_numpy(normalized.transpose(2, 0, 1)).unsqueeze(0).to(device)
    pad_h = (32 - height % 32) % 32
    pad_w = (32 - width % 32) % 32
    if pad_h or pad_w:
        tensor = F.pad(tensor, (0, pad_w, 0, pad_h), mode="constant", value=0)

    try:
        with torch.no_grad():
            if device == "cuda":
                with torch.amp.autocast("cuda"):
                    probs = model(tensor).sigmoid()
            else:
                probs = model(tensor).sigmoid()
        prob_map_scaled = probs[0, 0, :height, :width].detach().cpu().numpy()
    finally:
        del tensor
        if "probs" in locals():
            del probs
        if device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()

    if (orig_w, orig_h) != (width, height):
        prob_map = cv2.resize(prob_map_scaled, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
        width, height = orig_h, orig_w  # opencv shape convention
        width, height = orig_w, orig_h
    else:
        prob_map = prob_map_scaled

    threshold = detector_threshold(model_id)
    mask = (prob_map > threshold).astype(np.uint8) * 255
    close_size = max(3, min(17, make_odd(int(round(min(width, height) * 0.008)))))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = max(30, int(width * height * detector_min_area_ratio()))
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < min_area or w < 4 or h < 4:
            continue
        pad = max(2, int(round(min(w, h) * 0.12)))
        boxes.append(clamp_detection_box({"x": x - pad, "y": y - pad, "w": w + pad * 2, "h": h + pad * 2, "score": 1.0, "label": "text"}, image_size))
    return sorted(non_max_suppression(merge_nearby_boxes(boxes, detector_merge_gap())), key=lambda item: (item["y"], item["x"]))


def convert_batchnorm_to_groupnorm(module: Any, nn_module: Any) -> None:
    for name, child in module.named_children():
        if isinstance(child, nn_module.BatchNorm2d):
            channels = child.num_features
            groups = 8
            if channels < groups or channels % groups != 0:
                groups = next((candidate for candidate in range(min(channels, 8), 1, -1) if channels % candidate == 0), 1)
            setattr(module, name, nn_module.GroupNorm(num_groups=groups, num_channels=channels))
        else:
            convert_batchnorm_to_groupnorm(child, nn_module)


def make_odd(value: int) -> int:
    return value if value % 2 else value + 1


def detector_allowed_labels(model_id: str | None = None) -> set[str]:
    if model_id:
        normalized = normalize_detector_model_id(model_id)
        defaults = DETECTOR_MODEL_DEFAULTS.get(normalized)
        if defaults and normalized != DEFAULT_DETECTOR_MODEL:
            return {
                item.strip().lower()
                for item in str(defaults.get("labels", "")).split(",")
                if item.strip()
            }
    return {
        item.strip().lower()
        for item in str(ai_value("rtdetrTextLabels", "RTDETR_TEXT_LABELS", "text_bubble,text_free")).split(",")
        if item.strip()
    }


def detector_label_allowed(label_name: str, allowed_labels: set[str]) -> bool:
    if not allowed_labels:
        return True
    normalized = label_name.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in allowed_labels:
        return True
    if "text" in normalized and allowed_labels.intersection({"text_free", "text_bubble"}):
        return True
    if normalized in {"balloon", "speech_balloon"} and allowed_labels.intersection({"balloon", "bubble", "text_bubble"}):
        return True
    if "bubble" in normalized and allowed_labels.intersection({"bubble", "text_bubble"}):
        return True
    return False


def detector_threshold(model_id: str | None = None) -> float:
    fallback = DETECTOR_MODEL_DEFAULTS.get(normalize_detector_model_id(model_id or ""), {}).get("threshold", 0.55)
    return float(ai_value("rtdetrThreshold", "RTDETR_THRESHOLD", fallback))


def detector_min_area_ratio() -> float:
    return max(0.0, float(ai_value("detectorMinAreaRatio", "DETECTOR_MIN_AREA_RATIO", 0.00008)))


def detector_merge_gap() -> int:
    return max(0, int(float(ai_value("detectorMergeGap", "DETECTOR_MERGE_GAP", 18))))


def clamp_detection_box(box: dict[str, float], image_size: tuple[int, int]) -> dict[str, float]:
    image_width, image_height = image_size
    x1 = max(0.0, float(box.get("x", 0)))
    y1 = max(0.0, float(box.get("y", 0)))
    x2 = min(float(image_width), x1 + max(0.0, float(box.get("w", 0))))
    y2 = min(float(image_height), y1 + max(0.0, float(box.get("h", 0))))
    return {**box, "x": x1, "y": y1, "w": max(0.0, x2 - x1), "h": max(0.0, y2 - y1)}


def non_max_suppression(boxes: list[dict[str, float]]) -> list[dict[str, float]]:
    kept: list[dict[str, float]] = []
    for box in sorted(boxes, key=lambda item: item.get("score", 0), reverse=True):
        if box["w"] <= 3 or box["h"] <= 3:
            continue
        if any(overlap_ratio(existing, box) > 0.45 for existing in kept):
            continue
        kept.append(box)
    return kept


def merge_nearby_boxes(boxes: list[dict[str, float]], max_gap: int) -> list[dict[str, float]]:
    if max_gap <= 0:
        return merge_close_boxes(boxes)
    merged: list[dict[str, float]] = []
    for box in boxes:
        current = dict(box)
        changed = True
        while changed:
            changed = False
            for index, existing in enumerate(merged):
                if not boxes_are_near(existing, current, max_gap):
                    continue
                current = union_detection_boxes(existing, current)
                merged.pop(index)
                changed = True
                break
        merged.append(current)
    return merged


def boxes_are_near(first: dict[str, float], second: dict[str, float], max_gap: int) -> bool:
    expanded = {
        "x": first["x"] - max_gap,
        "y": first["y"] - max_gap,
        "w": first["w"] + max_gap * 2,
        "h": first["h"] + max_gap * 2,
    }
    return overlap_ratio(expanded, second) > 0


def union_detection_boxes(first: dict[str, float], second: dict[str, float]) -> dict[str, float]:
    x1 = min(first["x"], second["x"])
    y1 = min(first["y"], second["y"])
    x2 = max(first["x"] + first["w"], second["x"] + second["w"])
    y2 = max(first["y"] + first["h"], second["y"] + second["h"])
    score = max(float(first.get("score", 0)), float(second.get("score", 0)))
    label = first.get("label") or second.get("label", "")
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "score": score, "label": label}


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
    return run_ocr_with_geometry(image_file, box)["text"]


def run_ocr_with_geometry(image_file: str | Path, box: dict[str, Any]) -> dict[str, Any]:
    crop_file = crop_box(Path(image_file), box)
    try:
        analysis = run_paddleocr_analysis(crop_file)
        text = sanitize_ocr_text(analysis["text"]) or detect_punctuation_text(crop_file)
        corners = ocr_corners_from_polygons(analysis.get("polygons") or [], box, crop_size(crop_file))
        result: dict[str, Any] = {"text": text}
        if corners:
            result["corners"] = corners
        bbox = box.get("bbox") or {}
        box_left = max(0, float(bbox.get("x", 0)))
        box_top = max(0, float(bbox.get("y", 0)))
        polygons = analysis.get("polygons") or []
        if polygons:
            global_polygons = [
                [(float(pt[0] + box_left), float(pt[1] + box_top)) for pt in poly]
                for poly in polygons
                if len(poly) >= 3
            ]
            if global_polygons:
                result["textPolygons"] = global_polygons
        return result
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
    return run_paddleocr_analysis(image_file)["text"]


def run_paddleocr_analysis(image_file: Path) -> dict[str, Any]:
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
        try:
            output = pipeline.predict(str(image_file))
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
            output = pipeline.predict(str(image_file))
        analysis = extract_paddle_analysis(output)
        if kind == "vl" and not analysis["polygons"]:
            try:
                geometry_output = run_paddleocr_geometry(image_file)
                geometry = extract_paddle_analysis(geometry_output)
                analysis["polygons"] = geometry["polygons"]
                if not analysis["text"]:
                    analysis["text"] = geometry["text"]
            except Exception:
                pass
        return analysis
    except Exception as error:
        raise RuntimeError(f"PaddleOCR-VL 1.5 OCR çalıştırılamadı: {error}") from error


def run_paddleocr_geometry(image_file: Path) -> Any:
    global _OCR_GEOMETRY_PIPELINE
    from paddleocr import PaddleOCR

    if _OCR_GEOMETRY_PIPELINE is None:
        _OCR_GEOMETRY_PIPELINE = PaddleOCR(
            lang=str(ai_value("ocrLanguage", "OCR_LANG", "en")),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    return _OCR_GEOMETRY_PIPELINE.predict(str(image_file))


def extract_paddle_analysis(output: Any) -> dict[str, Any]:
    return {
        "text": extract_paddle_text(output),
        "polygons": extract_paddle_polygons(output),
    }


def extract_paddle_text(output: Any) -> str:
    fragments: list[str] = []
    seen: set[int] = set()

    text_keys = {
        "text",
        "texts",
        "rec_text",
        "rec_texts",
        "text_content",
        "ocr_text",
        "transcription",
        "markdown",
        "markdown_text",
        "markdown_texts",
        "block_content",
        "content",
    }
    skip_string_keys = {
        "input_path",
        "page_path",
        "img_path",
        "image_path",
        "file_path",
        "save_path",
        "output_path",
        "path",
        "filename",
        "file",
        "model",
        "label",
        "labels",
        "category",
        "type",
        "orientation",
    }

    def add_fragment(value: str) -> None:
        for line in value.splitlines():
            text = remove_inline_ocr_artifacts(line.strip()).strip()
            if is_valid_ocr_text_fragment(text):
                fragments.append(text)

    def looks_like_scored_text(value: list[Any] | tuple[Any, ...]) -> bool:
        return len(value) >= 2 and isinstance(value[0], str) and is_number(value[1])

    def walk(value: Any, text_context: bool = False) -> None:
        if value is None:
            return
        if isinstance(value, str):
            if text_context:
                add_fragment(value)
            return
        if isinstance(value, dict):
            value_id = id(value)
            if value_id in seen:
                return
            seen.add(value_id)
            for item_key, item in value.items():
                normalized_key = str(item_key).lower()
                if normalized_key in skip_string_keys:
                    continue
                if normalized_key in text_keys:
                    walk(item, True)
            for item_key, item in value.items():
                normalized_key = str(item_key).lower()
                if normalized_key in text_keys or normalized_key in skip_string_keys:
                    continue
                if not isinstance(item, str):
                    walk(item, False)
            return
        if isinstance(value, (list, tuple)):
            value_id = id(value)
            if value_id in seen:
                return
            seen.add(value_id)
            if looks_like_scored_text(value):
                add_fragment(value[0])
                return
            for item in value:
                walk(item, text_context)
            return
        for attr in ("json", "res"):
            if hasattr(value, attr):
                try:
                    walk(getattr(value, attr), False)
                except Exception:
                    pass
        for attr in ("text", "markdown"):
            if hasattr(value, attr):
                try:
                    walk(getattr(value, attr), True)
                except Exception:
                    pass

    walk(output)
    return "\n".join(dict.fromkeys(fragments)).strip()


def sanitize_ocr_text(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        fragment = remove_inline_ocr_artifacts(line.strip()).strip()
        if is_valid_ocr_text_fragment(fragment):
            lines.append(fragment)
    return "\n".join(lines).strip()


def remove_inline_ocr_artifacts(text: str) -> str:
    return re.sub(
        r"\s*(?:[A-Za-z]:)?[/\\][^\n]*?\.ocr_[^\n]*?\.(?:png|jpe?g|webp|bmp|tiff?)(?:\s+(?:min|general))*",
        " ",
        text,
        flags=re.IGNORECASE,
    )


def is_valid_ocr_text_fragment(text: str) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    if normalized in {"min", "general"}:
        return False
    if looks_like_image_path(text):
        return False
    return True


def looks_like_image_path(text: str) -> bool:
    candidate = text.strip().strip("()[]<>\"'")
    if "/" not in candidate and "\\" not in candidate:
        return False
    return bool(re.search(r"\.(?:png|jpe?g|webp|bmp|tiff?)(?:$|[\"')>\]])", candidate, re.IGNORECASE))


def extract_paddle_polygons(output: Any) -> list[list[tuple[float, float]]]:
    polygons: list[list[tuple[float, float]]] = []
    seen: set[int] = set()

    def add_polygon(value: Any) -> None:
        polygon = to_polygon(value)
        if not polygon:
            return
        key = tuple((round(x, 2), round(y, 2)) for x, y in polygon)
        if key in {tuple((round(x, 2), round(y, 2)) for x, y in item) for item in polygons}:
            return
        polygons.append(polygon)

    def walk(value: Any) -> None:
        if value is None:
            return
        value_id = id(value)
        if value_id in seen:
            return
        seen.add(value_id)
        if isinstance(value, dict):
            for poly_key in ("rec_polys", "dt_polys", "polys", "boxes", "rec_boxes", "det_polys"):
                if poly_key in value:
                    add_polygon_list(value[poly_key])
            for poly_key in ("poly", "polygon", "points", "bbox"):
                if poly_key in value:
                    add_polygon(value[poly_key])
            for item in value.values():
                walk(item)
            return
        if isinstance(value, (list, tuple)):
            parse_legacy_ocr_items(value)
            for item in value:
                walk(item)
            return
        for attr in ("json", "res"):
            if hasattr(value, attr):
                try:
                    walk(getattr(value, attr))
                except Exception:
                    pass

    def add_polygon_list(value: Any) -> None:
        items = value.tolist() if hasattr(value, "tolist") else value
        if not isinstance(items, (list, tuple)):
            return
        for item in items:
            add_polygon(item)

    def parse_legacy_ocr_items(value: list[Any] | tuple[Any, ...]) -> None:
        for item in value:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            if to_polygon(item[0]):
                add_polygon(item[0])

    walk(output)
    return polygons


def to_polygon(value: Any) -> list[tuple[float, float]] | None:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) == 4 and all(is_number(item) for item in value):
        x1, y1, x2, y2 = [float(item) for item in value]
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    if len(value) >= 8 and all(is_number(item) for item in value[:8]):
        numbers = [float(item) for item in value[:8]]
        return [(numbers[index], numbers[index + 1]) for index in range(0, 8, 2)]
    points = []
    for item in value:
        if hasattr(item, "tolist"):
            item = item.tolist()
        if isinstance(item, dict) and is_number(item.get("x")) and is_number(item.get("y")):
            points.append((float(item["x"]), float(item["y"])))
        elif isinstance(item, (list, tuple)) and len(item) >= 2 and is_number(item[0]) and is_number(item[1]):
            points.append((float(item[0]), float(item[1])))
    if len(points) < 4:
        return None
    return ordered_polygon(points[:4])


def ordered_polygon(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    ordered = sorted(points, key=lambda point: math.atan2(point[1] - center_y, point[0] - center_x))
    start = min(range(len(ordered)), key=lambda index: ordered[index][0] + ordered[index][1])
    return ordered[start:] + ordered[:start]


def ocr_corners_from_polygons(
    polygons: list[list[tuple[float, float]]],
    box: dict[str, Any],
    size: tuple[int, int],
) -> dict[str, dict[str, float]] | None:
    if not ai_bool("ocrPerspectiveEnabled", "OCR_PERSPECTIVE_ENABLED", True):
        return None
    if not polygons or has_custom_box_corners(box):
        return None
    width, height = size
    if width <= 1 or height <= 1:
        return None
    angle = dominant_polygon_angle(polygons)
    min_angle = clamp_float(ai_value("ocrPerspectiveMinAngle", "OCR_PERSPECTIVE_MIN_ANGLE", 7), 0, 45, 7)
    if angle is None or abs(math.degrees(angle)) < min_angle:
        return None
    points = [
        (clamp_float(x, -width * 0.25, width * 1.25, x), clamp_float(y, -height * 0.25, height * 1.25, y))
        for polygon in polygons
        for x, y in polygon
    ]
    if len(points) < 4:
        return None
    corners = oriented_bounds(points, angle, width, height)
    if not corners:
        return None
    return {
        key: {"x": clamp_float(point[0] / width, -1.0, 2.0, 0.0), "y": clamp_float(point[1] / height, -1.0, 2.0, 0.0)}
        for key, point in zip(("tl", "tr", "br", "bl"), corners)
    }


def dominant_polygon_angle(polygons: list[list[tuple[float, float]]]) -> float | None:
    sine = 0.0
    cosine = 0.0
    total = 0.0
    for polygon in polygons:
        if len(polygon) < 4:
            continue
        for start, end in ((polygon[0], polygon[1]), (polygon[3], polygon[2])):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            if length < 4:
                continue
            angle = normalize_text_angle(math.atan2(dy, dx))
            sine += math.sin(angle * 2) * length
            cosine += math.cos(angle * 2) * length
            total += length
    if total <= 0:
        return None
    return normalize_text_angle(0.5 * math.atan2(sine, cosine))


def oriented_bounds(
    points: list[tuple[float, float]],
    angle: float,
    width: int,
    height: int,
) -> list[tuple[float, float]] | None:
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    projected = [(x * cos_a + y * sin_a, -x * sin_a + y * cos_a) for x, y in points]
    min_u = min(point[0] for point in projected)
    max_u = max(point[0] for point in projected)
    min_v = min(point[1] for point in projected)
    max_v = max(point[1] for point in projected)
    bounds_width = max_u - min_u
    bounds_height = max_v - min_v
    if bounds_width < 6 or bounds_height < 6:
        return None
    padding = clamp_float(ai_value("ocrPerspectivePadding", "OCR_PERSPECTIVE_PADDING", 1.0), 0, 3, 1.0)
    pad_u = max(4.0, min(18.0, bounds_width * 0.08, width * 0.05)) * padding
    pad_v = max(4.0, min(16.0, bounds_height * 0.14, height * 0.07)) * padding
    min_u -= pad_u
    max_u += pad_u
    min_v -= pad_v
    max_v += pad_v

    def inverse(u: float, v: float) -> tuple[float, float]:
        return (u * cos_a - v * sin_a, u * sin_a + v * cos_a)

    return [
        inverse(min_u, min_v),
        inverse(max_u, min_v),
        inverse(max_u, max_v),
        inverse(min_u, max_v),
    ]


def normalize_text_angle(angle: float) -> float:
    while angle <= -math.pi / 2:
        angle += math.pi
    while angle > math.pi / 2:
        angle -= math.pi
    return angle


def crop_size(image_file: Path) -> tuple[int, int]:
    with Image.open(image_file) as image:
        return image.size


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed)


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
    texts = [sanitize_ocr_text(text) or text for text in texts]
    api_key = active_gemini_api_key()
    if not api_key:
        raise RuntimeError("Gemini çalışması için Ayarlar menüsünden aktif API key seçilmeli.")
    try:
        model = normalize_model_name(ai_value("geminiModel", "GEMINI_MODEL", "gemini-3-flash-preview"))
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

    model = normalize_model_name(model)
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


def normalize_model_name(value: Any) -> str:
    model = str(value or "").strip()
    if model.startswith("models/"):
        return model.removeprefix("models/").strip()
    return model


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
    text = remove_inline_ocr_artifacts(text)
    text = text.strip().strip('"').strip()
    return re.sub(r"\s+", " ", text)


def strip_number_prefix(line: str) -> str:
    return re.sub(r"^\s*\d+\s*[\.\):\-]\s*", "", line).strip()


def inpaint_region(image_file: str | Path, box: dict[str, Any]) -> dict[str, str]:
    image_file = Path(image_file)
    with TemporaryDirectory() as temp_dir:
        mask_file = Path(temp_dir) / "mask.png"
        create_mask(image_file, mask_file, box)
        run_iopaint(image_file, mask_file)
    return {"status": "cleaned", "engine": MODEL_REGISTRY["inpaint"]}


def inpaint_mask(image_file: str | Path, mask_file: str | Path) -> dict[str, str]:
    run_iopaint(Path(image_file), Path(mask_file))
    return {"status": "cleaned", "engine": MODEL_REGISTRY["inpaint"]}


def run_iopaint(image_file: Path, source_mask_file: Path) -> None:
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
            source = image.convert("RGB")
            source.save(input_file, format="PNG")
            with Image.open(source_mask_file) as source_mask:
                mask = source_mask.convert("L")
                if mask.size != source.size:
                    mask = mask.resize(source.size, NEAREST_RESAMPLE)
                mask.save(mask_file, format="PNG")
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
    from PIL import ImageFilter

    with Image.open(image_file) as image:
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        pad = int(ai_value("inpaintPadding", "INPAINT_PADDING", 8))
        text_polygons = box.get("textPolygons")
        if text_polygons:
            for poly in text_polygons:
                if len(poly) >= 3:
                    draw.polygon([(float(x), float(y)) for x, y in poly], fill=255)
            filter_size = max(3, pad * 2 + 1)
            if filter_size % 2 == 0:
                filter_size += 1
            mask = mask.filter(ImageFilter.MaxFilter(size=filter_size))
        elif ai_bool("inpaintPerspectiveMask", "INPAINT_PERSPECTIVE_MASK", True) and has_custom_box_corners(box):
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


def is_detector_loaded() -> bool:
    global _RTDETR_MODEL, _RTDETR_ONNX, _YOLO_MODELS, _MANGA_TEXT_SEGMENTATION_CACHE
    return bool(_RTDETR_MODEL is not None or _RTDETR_ONNX is not None or _YOLO_MODELS or _MANGA_TEXT_SEGMENTATION_CACHE)


def is_ocr_loaded() -> bool:
    global _OCR_PIPELINE, _OCR_GEOMETRY_PIPELINE
    return bool(_OCR_PIPELINE is not None or _OCR_GEOMETRY_PIPELINE is not None)


def preload_detector_model(model_id: str | None = None) -> dict[str, Any]:
    model_id = normalize_detector_model_id(str(model_id or ai_value("rtdetrModelId", "RTDETR_MODEL_ID", DEFAULT_DETECTOR_MODEL)).strip())
    dummy_img = Image.new("RGB", (64, 64), "white")
    with TemporaryDirectory() as temp_dir:
        dummy_path = Path(temp_dir) / "dummy.png"
        dummy_img.save(dummy_path)
        detect_with_configured_model(dummy_path)
    info = detector_model_info(model_id)
    return {"status": "loaded", "model": info["title"], "modelId": model_id, "family": info["family"]}


def preload_ocr_model() -> dict[str, Any]:
    dummy_img = Image.new("RGB", (64, 32), "white")
    with TemporaryDirectory() as temp_dir:
        dummy_path = Path(temp_dir) / "dummy.png"
        dummy_img.save(dummy_path)
        run_paddleocr_analysis(dummy_path)
    return {"status": "loaded", "model": MODEL_REGISTRY["ocr"]}


def unload_detector_model() -> dict[str, Any]:
    global _RTDETR_MODEL, _RTDETR_PROCESSOR, _RTDETR_MODEL_ID, _RTDETR_ONNX, _RTDETR_ONNX_MODEL_ID, _YOLO_MODELS, _MANGA_TEXT_SEGMENTATION_CACHE
    import gc

    _RTDETR_MODEL = None
    _RTDETR_PROCESSOR = None
    _RTDETR_MODEL_ID = ""
    _RTDETR_ONNX = None
    _RTDETR_ONNX_MODEL_ID = ""
    _YOLO_MODELS.clear()
    _MANGA_TEXT_SEGMENTATION_CACHE.clear()

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()
    return {"status": "unloaded", "model": "detector"}


def unload_ocr_model() -> dict[str, Any]:
    global _OCR_PIPELINE, _OCR_GEOMETRY_PIPELINE
    import gc

    _OCR_PIPELINE = None
    _OCR_GEOMETRY_PIPELINE = None

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()
    return {"status": "unloaded", "model": "ocr"}


def get_ai_models_status() -> dict[str, Any]:
    detector_info = current_detector_model_info()
    return {
        "detector": {
            "loaded": is_detector_loaded(),
            "activeModel": detector_info["title"],
            "modelId": detector_info["id"],
        },
        "ocr": {
            "loaded": is_ocr_loaded(),
            "activeModel": MODEL_REGISTRY["ocr"],
            "lang": str(ai_value("ocrLanguage", "OCR_LANG", "en")),
        },
        "inpaint": {
            "model": str(ai_value("inpaintModel", "IOPAINT_MODEL", "lama")),
            "device": str(ai_value("aiDevice", "AI_DEVICE", "cpu")),
        },
    }


from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .settings import ai_value, clamp_float
from .services.ai import detect_text_regions, inpaint_region, run_ocr, translate_texts
from .storage import add_box, backup_image, image_path, load_state, page_records, render_texts, save_state, update_box


@dataclass
class Job:
    id: str
    type: str
    status: str = "queued"
    progress: int = 0
    message: str = ""
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


JOBS: list[dict[str, Any]] = []


def create_job(kind: str, message: str = "") -> dict[str, Any]:
    job = asdict(Job(id=uuid4().hex, type=kind, message=message))
    JOBS.insert(0, job)
    return job


def complete(job: dict[str, Any], message: str) -> dict[str, Any]:
    job["status"] = "done"
    job["progress"] = 100
    job["message"] = message
    return job


def fail(job: dict[str, Any], error: Exception) -> dict[str, Any]:
    job["status"] = "failed"
    job["message"] = str(error)
    return job


def list_jobs() -> list[dict[str, Any]]:
    return JOBS[:50]


def detect(project_id: str, episode_id: str) -> dict[str, Any]:
    job = create_job("detect", "Yazı alanları tespit ediliyor")
    try:
        state = load_state(project_id, episode_id)
        state["boxes"] = [
            box
            for box in state["boxes"]
            if box.get("sourceText") or box.get("translatedText") or box.get("status") not in {"draft", ""}
        ]
        save_state(project_id, episode_id, state)
        existing = state["boxes"]
        created = 0
        for page in page_records(project_id, episode_id):
            page_existing = [box for box in existing if box["pageId"] == page["id"]]
            for bbox in detect_text_regions(page, image_path(project_id, episode_id, page["id"])):
                if any(overlap_ratio(box["bbox"], bbox) > 0.55 for box in page_existing):
                    continue
                box = add_box(project_id, episode_id, {"pageId": page["id"], "bbox": bbox})
                page_existing.append(box)
                existing.append(box)
                created += 1
        return complete(job, f"Yazı tespiti tamamlandı. {created} yeni yazı kutusu eklendi.")
    except Exception as error:
        return fail(job, error)


def overlap_ratio(first: dict[str, float], second: dict[str, float]) -> float:
    x1 = max(first["x"], second["x"])
    y1 = max(first["y"], second["y"])
    x2 = min(first["x"] + first["w"], second["x"] + second["w"])
    y2 = min(first["y"] + first["h"], second["y"] + second["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    smaller = min(first["w"] * first["h"], second["w"] * second["h"])
    return intersection / smaller if smaller else 0


def ocr(project_id: str, episode_id: str, box_ids: list[str] | None = None) -> dict[str, Any]:
    job = create_job("ocr", "OCR çalışıyor")
    try:
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        for box in state["boxes"]:
            if box["id"] in ids:
                update_box(
                    project_id,
                    episode_id,
                    box["id"],
                    {"sourceText": run_ocr(image_path(project_id, episode_id, box["pageId"]), box), "status": "ocr"},
                )
        return complete(job, "OCR tamamlandı")
    except Exception as error:
        return fail(job, error)


def translate(project_id: str, episode_id: str, target_language: str) -> dict[str, Any]:
    job = create_job("translate", "Çeviri yapılıyor")
    try:
        state = load_state(project_id, episode_id)
        candidates = [box for box in state["boxes"] if box.get("sourceText") and not box.get("translatedText")]
        if not candidates:
            return complete(job, "Çevrilecek metin yok.")

        pages = page_records(project_id, episode_id)
        chunks = translation_page_chunks(candidates, pages)
        translated_count = 0
        for index, chunk in enumerate(chunks, start=1):
            chunk_boxes = [box for page_id in chunk for box in page_candidates(candidates, page_id)]
            if not chunk_boxes:
                continue
            job["message"] = f"Çeviri yapılıyor ({index}/{len(chunks)} parça)"
            job["progress"] = max(1, int(((index - 1) / max(1, len(chunks))) * 90))
            translations = translate_texts([box["sourceText"] for box in chunk_boxes], target_language)
            for box, translated in zip(chunk_boxes, translations):
                update_box(project_id, episode_id, box["id"], {"translatedText": translated, "status": "translated"})
                translated_count += 1
        return complete(job, f"Çeviri tamamlandı. {translated_count} metin {len(chunks)} parçada işlendi.")
    except Exception as error:
        return fail(job, error)


def page_candidates(candidates: list[dict[str, Any]], page_id: str) -> list[dict[str, Any]]:
    return sorted(
        [box for box in candidates if box.get("pageId") == page_id],
        key=lambda box: (float(box.get("bbox", {}).get("y", 0)), float(box.get("bbox", {}).get("x", 0))),
    )


def translation_page_chunks(candidates: list[dict[str, Any]], pages: list[dict[str, Any]]) -> list[list[str]]:
    candidate_page_ids = {box.get("pageId") for box in candidates}
    ordered_page_ids = [page["id"] for page in pages if page.get("id")]
    if not ordered_page_ids:
        ordered_page_ids = list(dict.fromkeys(str(box.get("pageId")) for box in candidates if box.get("pageId")))
    split_count = int(clamp_float(ai_value("geminiPageSplits", "GEMINI_PAGE_SPLITS", 2), 1, 8, 2))
    return [
        chunk
        for chunk in split_evenly(ordered_page_ids, split_count)
        if any(page_id in candidate_page_ids for page_id in chunk)
    ]


def split_evenly(items: list[Any], parts: int) -> list[list[Any]]:
    if not items:
        return []
    parts = max(1, min(int(parts), len(items)))
    base_size, extra = divmod(len(items), parts)
    chunks = []
    start = 0
    for index in range(parts):
        size = base_size + (1 if index < extra else 0)
        chunks.append(items[start : start + size])
        start += size
    return chunks


def inpaint(project_id: str, episode_id: str, box_ids: list[str] | None = None) -> dict[str, Any]:
    job = create_job("inpaint", "Görsel temizleniyor")
    try:
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        for box in state["boxes"]:
            if box["id"] in ids:
                backup_image(project_id, episode_id, box["pageId"])
                inpaint_region(image_path(project_id, episode_id, box["pageId"]), box)
                update_box(project_id, episode_id, box["id"], {"status": "cleaned"})
        return complete(job, "Temizleme tamamlandı")
    except Exception as error:
        return fail(job, error)


def place(project_id: str, episode_id: str, box_ids: list[str] | None = None) -> dict[str, Any]:
    job = create_job("place", "Metinler yerleştiriliyor")
    try:
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        placed = 0
        for box in state["boxes"]:
            if box["id"] in ids and box.get("translatedText"):
                box["status"] = "placed"
                placed += 1
        save_state(project_id, episode_id, state)
        return complete(job, f"Metin yerleşimleri hazırlandı. {placed} kutu yerleştirildi.")
    except Exception as error:
        return fail(job, error)


def unplace(project_id: str, episode_id: str, box_ids: list[str] | None = None) -> dict[str, Any]:
    job = create_job("unplace", "Yerleşimler kaldırılıyor")
    try:
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        removed = 0
        for box in state["boxes"]:
            if box["id"] in ids and box.get("status") == "placed":
                box["status"] = "translated" if box.get("translatedText") else "draft"
                removed += 1
        save_state(project_id, episode_id, state)
        return complete(job, f"Yerleşim kaldırıldı. {removed} kutu güncellendi.")
    except Exception as error:
        return fail(job, error)


def save_images(project_id: str, episode_id: str) -> dict[str, Any]:
    job = create_job("save", "Görseller kaydediliyor")
    try:
        state = load_state(project_id, episode_id)
        pages = {box["pageId"] for box in state["boxes"]}
        for page_id in pages:
            render_texts(project_id, episode_id, page_id, [box for box in state["boxes"] if box["pageId"] == page_id])
        return complete(job, "Düzenlenmiş görseller kaydedildi")
    except Exception as error:
        return fail(job, error)

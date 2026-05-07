from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PROJECTS_DIR
from .settings import ai_value, clamp_float, load_settings
from .services.ai import detect_text_regions, inpaint_mask, inpaint_region, run_ocr_with_geometry, translate_texts
from .storage import (
    add_box,
    add_manual_mask,
    backup_image,
    begin_image_history,
    image_path,
    load_state,
    manual_mask_path,
    page_records,
    record_image_history,
    render_texts,
    restore_brush_from_original,
    save_state,
    update_box,
    update_manual_mask,
)


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


def start(job: dict[str, Any], message: str | None = None) -> dict[str, Any]:
    job["status"] = "running"
    job["progress"] = max(1, int(job.get("progress") or 0))
    if message:
        job["message"] = message
    return job


def advance(job: dict[str, Any], progress: int, message: str | None = None) -> dict[str, Any]:
    job["status"] = "running"
    job["progress"] = max(1, min(99, int(progress)))
    if message:
        job["message"] = message
    return job


def complete(job: dict[str, Any], message: str) -> dict[str, Any]:
    job["status"] = "done"
    job["progress"] = 100
    job["message"] = message
    job["completedAt"] = datetime.now(timezone.utc).isoformat()
    return job


def fail(job: dict[str, Any], error: Exception) -> dict[str, Any]:
    job["status"] = "failed"
    job["message"] = str(error)
    job["completedAt"] = datetime.now(timezone.utc).isoformat()
    return job


def list_jobs() -> list[dict[str, Any]]:
    return JOBS[:50]


def detect(project_id: str, episode_id: str) -> dict[str, Any]:
    job = create_job("detect", "Yazı alanları tespit ediliyor")
    try:
        start(job)
        state = load_state(project_id, episode_id)
        state["boxes"] = [
            box
            for box in state["boxes"]
            if box.get("sourceText") or box.get("translatedText") or box.get("status") not in {"draft", ""}
        ]
        save_state(project_id, episode_id, state)
        existing = state["boxes"]
        created = 0
        pages = page_records(project_id, episode_id)
        total = max(1, len(pages))
        for index, page in enumerate(pages, start=1):
            advance(job, int(((index - 1) / total) * 95), f"Yazı alanları tespit ediliyor ({index}/{total})")
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
        start(job)
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        selected = [box for box in state["boxes"] if box["id"] in ids]
        total = max(1, len(selected))
        for index, box in enumerate(selected, start=1):
            advance(job, int(((index - 1) / total) * 95), f"OCR çalışıyor ({index}/{total})")
            result = run_ocr_with_geometry(image_path(project_id, episode_id, box["pageId"]), box)
            patch = {"sourceText": result["text"], "status": "ocr"}
            if result.get("corners"):
                patch["corners"] = result["corners"]
            update_box(
                project_id,
                episode_id,
                box["id"],
                patch,
            )
        return complete(job, "OCR tamamlandı")
    except Exception as error:
        return fail(job, error)


def translate(project_id: str, episode_id: str, target_language: str) -> dict[str, Any]:
    job = create_job("translate", "Çeviri yapılıyor")
    try:
        start(job)
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
            advance(job, max(1, int(((index - 1) / max(1, len(chunks))) * 90)), f"Çeviri yapılıyor ({index}/{len(chunks)} parça)")
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
        start(job)
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        selected = [box for box in state["boxes"] if box["id"] in ids]
        total = max(1, len(selected))
        for index, box in enumerate(selected, start=1):
            advance(job, int(((index - 1) / total) * 95), f"Görsel temizleniyor ({index}/{total})")
            history = begin_image_history(project_id, episode_id, box["pageId"], "box-inpaint", {"boxId": box["id"]})
            backup_image(project_id, episode_id, box["pageId"])
            inpaint_region(image_path(project_id, episode_id, box["pageId"]), box)
            record_image_history(project_id, episode_id, history)
            update_box(project_id, episode_id, box["id"], {"status": "cleaned"})
        return complete(job, "Temizleme tamamlandı")
    except Exception as error:
        return fail(job, error)


def manual_inpaint(
    project_id: str,
    episode_id: str,
    page_id: str,
    mask_payload: str,
    bbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = create_job("manual-inpaint", "Fırça alanı temizleniyor")
    mask_record = None
    try:
        start(job)
        history = begin_image_history(project_id, episode_id, page_id, "manual-inpaint")
        advance(job, 12, "Fırça maskesi hazırlanıyor")
        mask_record = add_manual_mask(project_id, episode_id, page_id, mask_payload, bbox)
        history["meta"] = {"maskId": mask_record["id"]}
        advance(job, 24, "Temizlik öncesi yedek alınıyor")
        backup_image(project_id, episode_id, page_id)
        advance(job, 35, "IOPaint çalışıyor")
        inpaint_mask(image_path(project_id, episode_id, page_id), manual_mask_path(project_id, episode_id, mask_record))
        record_image_history(project_id, episode_id, history, mask_record.get("maskFile"))
        update_manual_mask(project_id, episode_id, mask_record["id"], {"status": "cleaned"})
        return complete(job, "Fırça temizliği tamamlandı")
    except Exception as error:
        if mask_record is not None:
            update_manual_mask(project_id, episode_id, mask_record["id"], {"status": "failed"})
        return fail(job, error)


def restore_brush(
    project_id: str,
    episode_id: str,
    page_id: str,
    mask_payload: str,
    bbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = create_job("restore-brush", "Orijinal piksel geri getiriliyor")
    try:
        start(job)
        history = begin_image_history(project_id, episode_id, page_id, "restore-brush")
        advance(job, 30, "Geri getirme maskesi hazırlanıyor")
        mask_record = restore_brush_from_original(project_id, episode_id, page_id, mask_payload, bbox)
        record_image_history(project_id, episode_id, history, mask_record.get("maskFile"))
        return complete(job, "Orijinal pikseller geri getirildi")
    except Exception as error:
        return fail(job, error)


def place(project_id: str, episode_id: str, box_ids: list[str] | None = None) -> dict[str, Any]:
    job = create_job("place", "Metinler yerleştiriliyor")
    try:
        start(job)
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        placed = 0
        selected = [box for box in state["boxes"] if box["id"] in ids]
        total = max(1, len(selected))
        for index, box in enumerate(selected, start=1):
            advance(job, int(((index - 1) / total) * 95), f"Metinler yerleştiriliyor ({index}/{total})")
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
        start(job)
        state = load_state(project_id, episode_id)
        ids = set(box_ids or [box["id"] for box in state["boxes"]])
        removed = 0
        selected = [box for box in state["boxes"] if box["id"] in ids]
        total = max(1, len(selected))
        for index, box in enumerate(selected, start=1):
            advance(job, int(((index - 1) / total) * 95), f"Yerleşimler kaldırılıyor ({index}/{total})")
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
        start(job)
        state = load_state(project_id, episode_id)
        pages = sorted({box["pageId"] for box in state["boxes"]})
        total = max(1, len(pages))
        for index, page_id in enumerate(pages, start=1):
            advance(job, int(((index - 1) / total) * 90), f"Görseller kaydediliyor ({index}/{total})")
            render_texts(project_id, episode_id, page_id, [box for box in state["boxes"] if box["pageId"] == page_id])
        advance(job, 92, "Reader senkronizasyonu yapılıyor")
        sync_to_reader(project_id, episode_id)
        return complete(job, "Düzenlenmiş görseller kaydedildi")
    except Exception as error:
        return fail(job, error)


def sync_to_reader(project_id: str, episode_id: str) -> None:
    settings = load_settings()
    reader = settings.get("reader", {})
    if not reader.get("syncEnabled"):
        return
    sync_host = reader.get("syncHost", "").strip()
    sync_path = normalize_remote_sync_path(sync_host, reader.get("syncPath", "").strip())
    if not sync_host or not sync_path:
        return
    episode_dir = PROJECTS_DIR / project_id / episode_id
    if not episode_dir.exists():
        return
    edited_dir = episode_dir / "Duzenlenmis"
    if not edited_dir.exists():
        edited_dir = episode_dir / "Edited"
    if not edited_dir.exists():
        return

    dest = f"{sync_host}:{sync_path}/{project_id}/{episode_id}/"
    command = [
        "rsync",
        "-avz",
        "--partial",
        "--delay-updates",
        "--mkpath",
        "--protect-args",
        "--timeout=30",
        "-e",
        "ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=4",
        f"{edited_dir}/",
        dest,
    ]
    last_detail = ""
    for attempt in range(1, 4):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode == 0:
                return
            last_detail = (result.stderr or result.stdout or "").strip()
        except Exception as error:
            last_detail = str(error)
        logging.getLogger(__name__).warning(
            "Reader sync failed for %s/%s on attempt %s: %s",
            project_id,
            episode_id,
            attempt,
            last_detail,
        )
        if attempt < 3:
            time.sleep(2 * attempt)
    raise RuntimeError(f"Reader sync failed for {project_id}/{episode_id}: {last_detail}")


def normalize_remote_sync_path(sync_host: str, sync_path: str) -> str:
    if sync_path == "~" or sync_path.startswith("~/"):
        remote_user = sync_host.split("@", 1)[0].strip() if "@" in sync_host else ""
        if remote_user:
            suffix = sync_path[2:] if sync_path.startswith("~/") else ""
            return f"/home/{remote_user}/{suffix}".rstrip("/")
    return sync_path

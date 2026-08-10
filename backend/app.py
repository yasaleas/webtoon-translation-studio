from pathlib import Path
from io import BytesIO
import os

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from . import jobs
from .fonts import font_path, list_fonts, upload_font
from .project_metadata import download_cover, fetch_and_store_project_metadata, search_project_metadata
from .services.ai import (
    get_ai_models_status,
    preload_detector_model,
    preload_ocr_model,
    unload_detector_model,
    unload_ocr_model,
)
from .settings import public_settings, save_settings
from .storage import (
    add_box,
    apply_text_style,
    clear_project_metadata,
    delete_box,
    image_path,
    list_episodes,
    list_projects,
    load_state,
    load_project_metadata,
    manual_mask_overlay,
    merge_page_with_next,
    page_records,
    project_cover_path,
    redo_image_history,
    restore_box_from_original,
    restore_manual_mask_from_original,
    save_project_metadata,
    save_project_cover,
    undo_image_history,
    update_box,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("WEBTOON_MAX_UPLOAD_MB", "25")) * 1024 * 1024
    CORS(app, resources={r"/api/*": {"origins": cors_origins()}})

    def with_reader_metadata_sync(project_id: str, metadata: dict):
        try:
            jobs.sync_project_metadata_to_reader(project_id)
        except RuntimeError as error:
            metadata["readerSyncError"] = str(error)
        return metadata

    def with_reader_metadata_clear(project_id: str, metadata: dict):
        try:
            jobs.clear_project_metadata_from_reader(project_id)
        except RuntimeError as error:
            metadata["readerSyncError"] = str(error)
        return metadata

    @app.errorhandler(ValueError)
    def bad_request(error: ValueError):
        return {"error": str(error)}, 400

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/ocr_status")
    def ocr_status():
        return {
            "ok": True,
            "detector": "RT-DETR V2, YOLO segmenter ve Manga text segmentation",
            "ocr": "PaddleOCR-VL 1.5",
            "inpaint": "IOPaint LaMa",
            "translation": "Gemini API",
        }

    @app.get("/api/models/status")
    def models_status():
        return jsonify(get_ai_models_status())

    @app.post("/api/models/preload")
    def preload_model_route():
        payload = request.get_json(silent=True) or {}
        target = payload.get("model", "detector").lower()
        if target == "detector":
            return jsonify(preload_detector_model(payload.get("modelId")))
        elif target == "ocr":
            return jsonify(preload_ocr_model())
        return {"error": f"Bilinmeyen model tipi: {target}"}, 400

    @app.post("/api/models/unload")
    def unload_model_route():
        payload = request.get_json(silent=True) or {}
        target = payload.get("model", "all").lower()
        if target == "detector":
            return jsonify(unload_detector_model())
        elif target == "ocr":
            return jsonify(unload_ocr_model())
        elif target == "all":
            res_d = unload_detector_model()
            res_o = unload_ocr_model()
            return jsonify({"status": "unloaded", "detector": res_d, "ocr": res_o})
        return {"error": f"Bilinmeyen model tipi: {target}"}, 400

    @app.get("/api/fonts")
    def fonts():
        return jsonify(list_fonts())

    @app.get("/api/fonts/<font_id>/file")
    def font_file(font_id: str):
        path = font_path(font_id)
        if path is None:
            return {"error": "font not found"}, 404
        return send_file(path)

    @app.post("/api/fonts/upload")
    def font_upload():
        try:
            return jsonify(upload_font(request.files.get("font"), request.form.get("name", "")))
        except ValueError as error:
            return {"error": str(error)}, 400

    @app.get("/api/settings")
    def settings():
        return jsonify(public_settings())

    @app.put("/api/settings")
    def update_settings():
        return jsonify(save_settings(request.get_json(force=True)))

    @app.get("/api/projects")
    def projects():
        return jsonify(list_projects())

    @app.get("/api/projects/<project_id>/cover")
    def project_cover(project_id: str):
        path = project_cover_path(project_id)
        if path is None:
            return {"error": "cover not found"}, 404
        return send_file(path)

    @app.get("/api/metadata/cover-preview")
    def metadata_cover_preview():
        url = request.args.get("url", "")
        if not url:
            return {"error": "cover url required"}, 400
        try:
            content, content_type = download_cover(url)
        except RuntimeError as error:
            return {"error": str(error)}, 502
        return send_file(BytesIO(content), mimetype=content_type or "image/jpeg")

    @app.post("/api/projects/<project_id>/cover/upload")
    def upload_project_cover(project_id: str):
        cover = request.files.get("cover")
        if cover is None or not cover.filename:
            return {"error": "cover not found"}, 400
        try:
            return jsonify(with_reader_metadata_sync(project_id, save_project_cover(project_id, cover.read(), cover.filename, cover.content_type or "")))
        except ValueError as error:
            return {"error": str(error)}, 400

    @app.get("/api/projects/<project_id>/metadata")
    def project_metadata(project_id: str):
        return jsonify(load_project_metadata(project_id))

    @app.put("/api/projects/<project_id>/metadata")
    def update_project_metadata(project_id: str):
        return jsonify(with_reader_metadata_sync(project_id, save_project_metadata(project_id, request.get_json(force=True))))

    @app.delete("/api/projects/<project_id>/metadata")
    def delete_project_metadata(project_id: str):
        return jsonify(with_reader_metadata_clear(project_id, clear_project_metadata(project_id)))

    @app.post("/api/projects/<project_id>/metadata/fetch")
    def fetch_project_metadata(project_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(
                with_reader_metadata_sync(
                    project_id,
                    fetch_and_store_project_metadata(
                        project_id,
                        query=payload.get("query"),
                        provider=payload.get("provider", "anilist"),
                        source_id=payload.get("sourceId"),
                    ),
                )
            )
        except RuntimeError as error:
            return {"error": str(error)}, 502
        except ValueError as error:
            return {"error": str(error)}, 400

    @app.post("/api/projects/<project_id>/metadata/search")
    def search_project_metadata_route(project_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(
                search_project_metadata(
                    project_id,
                    query=payload.get("query"),
                    provider=payload.get("provider", "all"),
                )
            )
        except RuntimeError as error:
            return {"error": str(error)}, 502
        except ValueError as error:
            return {"error": str(error)}, 400

    @app.get("/api/projects/<project_id>/episodes")
    def episodes(project_id: str):
        return jsonify(list_episodes(project_id))

    @app.post("/api/session/open")
    def open_session():
        payload = request.get_json(force=True)
        project_id = payload["projectId"]
        episode_id = payload["episodeId"]
        return jsonify(
            {
                "projectId": project_id,
                "episodeId": episode_id,
                "pages": page_records(project_id, episode_id),
                "state": load_state(project_id, episode_id),
            }
        )

    @app.get("/api/pages")
    def pages():
        return jsonify(page_records(request.args["projectId"], request.args["episodeId"]))

    @app.post("/api/pages/<path:page_id>/merge-next")
    def merge_next_page(page_id: str):
        payload = request.get_json(force=True)
        project_id = payload["projectId"]
        episode_id = payload["episodeId"]
        try:
            result = merge_page_with_next(project_id, episode_id, page_id)
        except FileNotFoundError as error:
            return {"error": str(error)}, 404
        except ValueError as error:
            return {"error": str(error)}, 400
        return jsonify(
            {
                "pages": page_records(project_id, episode_id),
                "state": load_state(project_id, episode_id),
                "merge": result,
            }
        )

    @app.get("/api/pages/<path:page_id>/image")
    def page_image(page_id: str):
        try:
            path = image_path(request.args["projectId"], request.args["episodeId"], page_id)
        except ValueError as error:
            return {"error": str(error)}, 400
        if not Path(path).exists():
            return {"error": "image not found"}, 404
        return send_file(path)

    @app.post("/api/boxes")
    def create_box():
        payload = request.get_json(force=True)
        return jsonify(add_box(payload["projectId"], payload["episodeId"], payload))

    @app.patch("/api/boxes/<box_id>")
    def patch_box(box_id: str):
        payload = request.get_json(force=True)
        box = update_box(payload["projectId"], payload["episodeId"], box_id, payload["patch"])
        if box is None:
            return {"error": "box not found"}, 404
        return jsonify(box)

    @app.post("/api/boxes/apply-style")
    def bulk_apply_style():
        payload = request.get_json(force=True)
        return jsonify(
            apply_text_style(
                payload["projectId"],
                payload["episodeId"],
                payload.get("style") or {},
                payload.get("boxIds"),
            )
        )

    @app.delete("/api/boxes/<box_id>")
    def remove_box(box_id: str):
        payload = request.get_json(force=True)
        if not delete_box(payload["projectId"], payload["episodeId"], box_id):
            return {"error": "box not found"}, 404
        return {"ok": True}

    @app.post("/api/boxes/<box_id>/restore-original")
    def restore_box(box_id: str):
        payload = request.get_json(force=True)
        try:
            box = restore_box_from_original(payload["projectId"], payload["episodeId"], box_id)
        except FileNotFoundError as error:
            return {"error": str(error)}, 404
        except ValueError as error:
            return {"error": str(error)}, 400
        if box is None:
            return {"error": "box not found"}, 404
        return jsonify(box)

    @app.post("/api/manual-masks/<mask_id>/restore-original")
    def restore_manual_mask(mask_id: str):
        payload = request.get_json(force=True)
        try:
            mask = restore_manual_mask_from_original(payload["projectId"], payload["episodeId"], mask_id)
        except FileNotFoundError as error:
            return {"error": str(error)}, 404
        except ValueError as error:
            return {"error": str(error)}, 400
        if mask is None:
            return {"error": "manual mask not found"}, 404
        return jsonify(mask)

    @app.get("/api/manual-masks/<mask_id>/overlay")
    def manual_mask_overlay_image(mask_id: str):
        try:
            buffer = manual_mask_overlay(request.args["projectId"], request.args["episodeId"], mask_id)
        except FileNotFoundError as error:
            return {"error": str(error)}, 404
        except ValueError as error:
            return {"error": str(error)}, 400
        if buffer is None:
            return {"error": "manual mask not found"}, 404
        return send_file(buffer, mimetype="image/png")

    @app.post("/api/history/undo")
    def undo_history():
        payload = request.get_json(force=True)
        try:
            entry = undo_image_history(payload["projectId"], payload["episodeId"])
        except FileNotFoundError as error:
            return {"error": str(error)}, 404
        if entry is None:
            return {"error": "undo stack empty"}, 404
        return jsonify(entry)

    @app.post("/api/history/redo")
    def redo_history():
        payload = request.get_json(force=True)
        try:
            entry = redo_image_history(payload["projectId"], payload["episodeId"])
        except FileNotFoundError as error:
            return {"error": str(error)}, 404
        if entry is None:
            return {"error": "redo stack empty"}, 404
        return jsonify(entry)

    @app.get("/api/jobs")
    def list_job_records():
        return jsonify(jobs.list_jobs())

    @app.post("/api/jobs/detect")
    def detect():
        payload = request.get_json(force=True)
        return jsonify(jobs.detect(payload["projectId"], payload["episodeId"]))

    @app.post("/api/jobs/ocr")
    def ocr():
        payload = request.get_json(force=True)
        return jsonify(jobs.ocr(payload["projectId"], payload["episodeId"], payload.get("boxIds")))

    @app.post("/api/jobs/inpaint")
    def inpaint():
        payload = request.get_json(force=True)
        return jsonify(jobs.inpaint(payload["projectId"], payload["episodeId"], payload.get("boxIds")))

    @app.post("/api/jobs/manual-inpaint")
    def manual_inpaint():
        payload = request.get_json(force=True)
        return jsonify(
            jobs.manual_inpaint(
                payload["projectId"],
                payload["episodeId"],
                payload["pageId"],
                payload["mask"],
                payload.get("bbox"),
            )
        )

    @app.post("/api/jobs/restore-brush")
    def restore_brush():
        payload = request.get_json(force=True)
        return jsonify(
            jobs.restore_brush(
                payload["projectId"],
                payload["episodeId"],
                payload["pageId"],
                payload["mask"],
                payload.get("bbox"),
            )
        )

    @app.post("/api/jobs/translate")
    def translate():
        payload = request.get_json(force=True)
        return jsonify(jobs.translate(payload["projectId"], payload["episodeId"], payload.get("targetLanguage", "TR")))

    @app.post("/api/jobs/place")
    def place():
        payload = request.get_json(force=True)
        return jsonify(jobs.place(payload["projectId"], payload["episodeId"], payload.get("boxIds")))

    @app.post("/api/jobs/unplace")
    def unplace():
        payload = request.get_json(force=True)
        return jsonify(jobs.unplace(payload["projectId"], payload["episodeId"], payload.get("boxIds")))

    @app.post("/api/jobs/save")
    def save_images():
        payload = request.get_json(force=True)
        return jsonify(jobs.save_images(payload["projectId"], payload["episodeId"]))

    return app


def cors_origins() -> list[str]:
    configured = os.getenv("WEBTOON_CORS_ORIGINS", "")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("WEBTOON_HOST", "127.0.0.1"),
        port=int(os.getenv("WEBTOON_PORT", "5000")),
        debug=os.getenv("WEBTOON_DEBUG", "0").lower() in {"1", "true", "yes", "on"},
    )

from pathlib import Path
import os

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from . import jobs
from .fonts import font_path, list_fonts, upload_font
from .settings import public_settings, save_settings
from .storage import (
    add_box,
    apply_text_style,
    delete_box,
    image_path,
    list_episodes,
    list_projects,
    load_state,
    page_records,
    restore_box_from_original,
    update_box,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("WEBTOON_MAX_UPLOAD_MB", "25")) * 1024 * 1024
    CORS(app, resources={r"/api/*": {"origins": cors_origins()}})

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
            "detector": "RT-DETR V2 text_bubble/text_free detection",
            "ocr": "PaddleOCR-VL 1.5",
            "inpaint": "IOPaint LaMa",
            "translation": "Gemini API",
        }

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

# Repository Guidelines

## Project Structure & Module Organization

This repository contains a local webtoon editing studio with a Flask API and a React/Vite frontend.

- `backend/`: Flask application code. `app.py` defines routes, `jobs.py` runs OCR/translation/inpaint/save workflows, `storage.py` manages project state and image rendering, and `services/ai.py` wraps detector/OCR/Gemini/IOPaint integrations.
- `frontend/src/`: React UI. `main.jsx` holds the app workflow, `lib/api.js` contains API calls, and `styles/app.css` contains the main stylesheet.
- `webtoon-downloader/`: downloader skill used to save chapter images into `data/projects`.
- `data/`: local runtime data, settings, uploaded fonts, and webtoon projects. Do not treat generated project images, backups, or state files as source code.
- `dist/`: Vite build output.
- `README.md` and `SISTEM_DOKUMANI.md`: setup and system context.

## Build, Test, and Development Commands

Install dependencies:

```bash
python3.11 -m venv .venv-ai
.venv-ai/bin/python -m pip install -r backend/requirements-ai.txt
npm install
```

Run locally:

```bash
.venv-ai/bin/python -m backend.app
npm run dev
```

Build frontend and check backend syntax:

```bash
npm run build
.venv-ai/bin/python -m compileall backend
```

## Coding Style & Naming Conventions

Use 4-space indentation in Python and 2-space indentation in React/CSS. Prefer clear function names such as `translate_texts`, `render_texts`, and `apply_text_style`. Keep React components in PascalCase and local helper functions in camelCase. Follow existing CSS class naming (`actionbar`, `text-preview`, `settings-section`) instead of introducing a new convention.

## Testing Guidelines

There is no formal test suite yet. Use focused smoke tests for changed backend behavior and always run `compileall` plus `npm run build` before handing off. For UI changes, verify the Vite app manually at the dev URL and check affected workflows such as OCR, inpaint, placement, and save.

## Commit & Pull Request Guidelines

This workspace is not currently a Git repository, so no project-specific commit history exists. Use concise imperative commit messages if Git is initialized later, for example `Fix multiline text rendering on save`. Pull requests should describe the user-facing change, list verification commands, mention AI/model setting changes, and include screenshots for UI updates.

## Security & Configuration Tips

Keep Gemini API keys out of source files. User-facing configuration is managed from the settings UI and stored locally in ignored runtime files such as `data/settings.json`. Avoid committing generated files under `data/projects/`, `data/settings.json`, `data/fonts/`, `.venv*`, `dist/`, and the personal `reader/` workspace unless explicitly needed.

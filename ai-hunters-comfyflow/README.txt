# AI Hunters ComfyFlow v1.0.0

**Import a ComfyUI workflow → it is converted to Python automatically → required models are downloaded
into the right folders → run it → preview and download images and videos.**
FastAPI backend + React (Vite) frontend on Windows 11. No Docker.

---

## Rules for this project (keep at the top of every delivery)

1. Project folder / repo name: `ai-hunters-comfyflow`.
2. Every delivery is a full new ZIP with an incremented version, e.g. `ai-hunters-comfyflow-v1.0.1.zip`.
   Never reuse a version number, even for a one-line change.
3. The version is stamped in `frontend/package.json`, `backend/app/__init__.py` (+ `backend/app/main.py` header),
   this README and the ZIP file name.
4. ZIP names never contain: patch, fixed, hotfix, modified, revised.
5. Windows 11 only, no Docker.
6. Ports are read from `.env` only: **frontend 5091, backend 3015** (ComfyUI 8188).
7. Light theme only (Claude-style warm ivory + terracotta). All browser messages are shown in modal dialogs.

---

## Quick start (Windows 11)

Prerequisites (install once, then open a new terminal):

```
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
winget install -e --id OpenJS.NodeJS.LTS
```

Then, in the project folder:

| Step | Command | What it does |
|---|---|---|
| 1 | `Setup.bat` | Creates `.env`, `backend\.venv`, installs Python + npm packages, **installs ComfyUI** into `comfyui\` with its own venv, PyTorch (CUDA 12.8 when an NVIDIA GPU is found, otherwise CPU + `--cpu`) and the custom nodes from `config\custom-nodes.txt`. Safe to re-run. |
| 2 | `Start-all.bat` | Starts ComfyUI (8188), backend (3015) and frontend (5091) in minimised windows and opens http://localhost:5091 |
| 3 | `Stop-all.bat` | Stops all three (use `Stop-all.bat keep-comfyui` to leave ComfyUI running) |

Already have ComfyUI? Set `INSTALL_COMFYUI=false` and `COMFYUI_HOST` / `COMFYUI_PORT` in `.env` before running Setup.bat.

## Using the app

* **New workflow (wizard)**
  1. *Select workflow* – drop a ComfyUI `.json`, browse for it, or type a path on this computer
     (the UI “Save” export and the “Export (API)” format both work). The backend converts it to
     `data\workflows\<id>\workflow.py` (viewable/downloadable from the UI).
  2. *Models* – every model file the workflow references is detected and matched with the model list.
     URLs embedded in the workflow are picked up automatically. Each row has its own **Download** button,
     plus *Download all missing* and an *Auto-download* switch. Rows without a URL can be edited in place.
     **Run unlocks only when every model is ready.**
  3. *Run & results* – edit prompts, seed, sizes and input images, run, follow live progress; results open
     automatically in the **Image preview** or **Video preview** modal with **Download** / **Download all**.
* **Models** – grid (5 per page) of all models: edit name, download URL, category and save location;
  add, delete, download, cancel. Downloads resume and run in the background.
* **Results** – every run with thumbnails, status, errors, preview and ZIP download.
* **Settings** – ComfyUI status/start, *Sync nodes from ComfyUI* (regenerates typed node classes for your
  custom nodes), models folder, parallel downloads, Hugging Face / Civitai tokens.

## Configuration (`.env`)

| Key | Default | Notes |
|---|---|---|
| `FRONTEND_PORT` / `BACKEND_PORT` | 5091 / 3015 | Only read from `.env`; the app refuses to start without them |
| `COMFYUI_HOST` / `COMFYUI_PORT` | 127.0.0.1 / 8188 | ComfyUI server used for runs |
| `COMFYUI_DIR`, `COMFYUI_PYTHON` | `comfyui\ComfyUI`, `comfyui\venv\Scripts\python.exe` | Installed by Setup.bat |
| `COMFYUI_EXTRA_ARGS` | empty (`--cpu` without NVIDIA GPU) | e.g. `--lowvram` |
| `MODELS_DIR` | empty = `<COMFYUI_DIR>\models` | A custom folder is registered with ComfyUI via `extra_model_paths.yaml` |
| `MAX_PARALLEL_DOWNLOADS` | 2 | 1–8 |
| `AUTO_DOWNLOAD_MODELS` | true | Wizard step 2 starts missing downloads automatically |
| `HF_TOKEN`, `CIVITAI_TOKEN` | empty | Only sent to huggingface.co / civitai.com |
| `DATA_DIR` | `data` | models.json, workflows, runs, outputs, uploads |

## Project structure

```
ai-hunters-comfyflow/
├─ Setup.bat · Start-all.bat · Stop-all.bat · .env.example
├─ config/custom-nodes.txt          ComfyUI custom nodes installed by Setup.bat
├─ scripts/setup_comfyui.py         ComfyUI + PyTorch + custom-node installer
├─ scripts/prestart.py              registers a custom MODELS_DIR with ComfyUI
├─ samples/                         sample workflow, images and video
├─ backend/
│  ├─ app/                          FastAPI app (python -m app)
│  │  ├─ config.py                  .env loader/writer
│  │  ├─ events.py                  SSE event bus (download + run progress)
│  │  ├─ routers/                   system · models · workflows · runs
│  │  ├─ services/                  registry · downloader · comfy · workflows · runs
│  │  └─ defaults/models.json       initial model list
│  ├─ cb2c_py/                      workflow library (typed nodes, Workflow, runner, converter)
│  ├─ tools/fake_comfyui.py         ComfyUI stand-in for tests and GPU-less demos
│  └─ tests/                        pytest suite (46 tests)
└─ frontend/                        React 18 + Vite, light theme, modal system
   └─ src/ pages · components · context · styles/theme-light.css
```

## API (backend, http://127.0.0.1:3015/docs)

`GET /api/system` · `GET /api/dashboard` · `GET|PUT /api/settings` · `POST /api/comfyui/start` ·
`POST /api/comfyui/sync-nodes` · `GET /api/events` (SSE) ·
`GET|POST /api/models` · `DELETE /api/models/{name}` · `POST /api/models/download|download-all|cancel` ·
`GET /api/workflows` · `POST /api/workflows/upload|import-path` · `GET|PATCH|DELETE /api/workflows/{id}` ·
`GET /api/workflows/{id}/script|models|parameters` · `POST /api/workflows/{id}/models/download-missing` ·
`POST|GET /api/runs` · `GET|DELETE /api/runs/{id}` · `POST /api/runs/{id}/cancel` ·
`GET /api/runs/{id}/files/{filename}[?download=1]` · `GET /api/runs/{id}/zip` · `POST|GET /api/uploads`

## Development

```
cd backend
.venv\Scripts\python -m pytest            # 46 tests, uses tools/fake_comfyui.py (no GPU needed)
.venv\Scripts\python -m tools.fake_comfyui --port 8188   # demo the UI without a GPU
```

## Troubleshooting

* **“ComfyUI not installed / offline”** – run `Setup.bat`, then `Start-all.bat`. The first ComfyUI start takes a minute.
* **A download fails with 401/403** – the model is gated: add a Hugging Face token in Settings (and accept the
  licence on the model page) or a Civitai key.
* **A node shows as GenericNode / widget values look wrong** – install the custom node (add it to
  `config\custom-nodes.txt`, re-run Setup.bat), start ComfyUI, click *Sync nodes from ComfyUI*, re-import the workflow.
* **Port already in use** – change the port in `.env`, then `Stop-all.bat` and `Start-all.bat`.

---
Based on the ComfyBack2Code library (MIT). © AI Hunters Zone.

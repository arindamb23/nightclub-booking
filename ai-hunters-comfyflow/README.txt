# AI Hunters ComfyFlow v1.0.5

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

Nothing needs to be installed beforehand. `Setup.bat` checks for each tool and downloads whatever is missing:

| Tool | If missing, Setup.bat… | Admin rights |
|---|---|---|
| Python 3.10–3.13 | installs Python 3.12.8 silently into `tools\python` (per-user) | not needed |
| Git | downloads portable MinGit into `tools\git` | not needed |
| Node.js | downloads portable Node.js 22 LTS into `tools\node` | not needed |
| Visual C++ runtime (for PyTorch) | downloads and installs `vc_redist.x64.exe` | Windows asks once |

Tools already installed on the PC are used as they are. The portable tools in `tools\` are only used by ComfyFlow
(Start-all.bat adds them to its own PATH); nothing is added to the system PATH. Delete `tools\` to remove them.

Then, in the project folder:

| Step | Command | What it does |
|---|---|---|
| 1 | `Setup.bat` | Downloads missing tools (above), creates `.env`, `backend\.venv`, installs Python + npm packages, **installs ComfyUI** into `comfyui\` with its own venv, PyTorch (CUDA 12.8 when an NVIDIA GPU is found, otherwise CPU + `--cpu`) and the custom nodes from `config\custom-nodes.txt`. Safe to re-run. |
| 2 | `Start-all.bat` | Starts ComfyUI (8188), backend (3015) and frontend (5091) in minimised windows and opens http://localhost:5091 |
| 3 | `Stop-all.bat` | Stops all three (use `Stop-all.bat keep-comfyui` to leave ComfyUI running) |

Already have ComfyUI? Set `INSTALL_COMFYUI=false` and `COMFYUI_HOST` / `COMFYUI_PORT` in `.env` before running Setup.bat.

## Using the app

* **Workflow editor** (*Workflows → Editor*) – the workflow as a clean node graph:
  * cards coloured by role (Input · Prompt · Model · Generate · Output) with a one-line summary, badges for
    run-time fields and model status, thumbnails of input media and the last result on output nodes;
  * connections coloured by data type (legend on the canvas); drag nodes, **Auto layout**, zoom/fit, minimap,
    **Find node**; **Simple view** folds all model loaders into one *Models* card, **Detailed view** shows every node;
  * click a node → the **properties panel** shows every setting as the right control (text, prompt, dropdown with
    the real options, number with its limits, switch, upload). Each setting has a **Run time** tick and a label;
  * media is uploaded **only through the Upload dialog**; ▶ on a node opens the image preview, or the video / audio
    player with **Play, Pause, Stop**, seek and Download;
  * output nodes have an **Expected output** (image / video / audio);
  * **Save** writes the values into `workflow.py` (the previous version is kept in `data\workflows\<id>\history\`)
    and stores run-time choices, labels and node positions; **Run** opens the Run screen.
* **Control map** – `config\controlmap.json` decides which inputs are uploads, prompts and outputs and whether they
  are **Run time by default** (uploads and prompts are). Exact node entries first, then patterns (so custom nodes
  with upload flags or prompt-like names are recognised too), then the node's ComfyUI definition. Edit the file to
  change the defaults for every workflow; changes are picked up without a restart.
* **Run screen** – shows exactly the run-time fields (with their labels and controls) and the expected outputs.

* **Generate** (sidebar) – one screen for the four common jobs, each powered by a Python *template*:

  | Task | Built-in template (`backend\cb2c_py\templates\workflow\`) | Inputs |
  |---|---|---|
  | Text to Image | `text2image.py` (SD 1.5 / SDXL checkpoints) | prompt, negative prompt, seed, size, checkpoint, sampler |
  | Text to Video | `wan2_1_text2video_gguf.py` (Wan 2.1 14B GGUF) | prompt, negative prompt, seed, duration, size |
  | Image to Video | `wan2_1_image2video_gguf.py` (Wan 2.1 14B 480p GGUF) | **input image + prompt**, negative prompt, seed, duration |
  | Image Edit | `omnigen2_image2image.py`, `flux_kontext_dev_nunchaku.py` | input image (+ optional 2nd image), instruction prompt |

  Upload a picture (or use a sample), write the prompt and press **Generate**. The models the template needs
  are **detected automatically** for the values you chose, downloaded if missing (the same “Models needed”
  dialog asks for a URL or file path when there is no working link), then the result opens in the
  image or video preview.
* **Your own templates** – *Generate → Add template (.py)*. A template is any Python function that returns a
  cb2c_py `Workflow`; its parameters become the form (names containing `prompt`, `image`/`image_path`, `seed`
  are recognised; numbers, booleans, `ckpt_name`/`model` get suitable inputs). Optionally add
  `TEMPLATE = {"name": ..., "task": "text_to_image|text_to_video|image_to_video|image_edit", "description": ...}`.
  Uploaded templates are stored in `data\templates\`.
* **Command-line runners** (as in the original project): `backend\cb2c_py\templates\runner\*.py`, e.g.
  `.venv\Scripts\python -m cb2c_py.templates.runner.wan2_1_image2video_gguf` from the `backend` folder
  (needs ComfyUI running and the models downloaded; set `DEBUG_JSON_WORKFLOW=true` to only print the JSON).

* **Sample library** – five ready-made workflows are added to the Workflows list on first start
  (they live in `samples\workflows\`):

  | Sample | File | Output |
  |---|---|---|
  | SD 1.5 Text to Image | `sd15_text2image.json` (ComfyUI UI export) | image |
  | SDXL RealVis Text to Image | `sdxl_realvis_text2image.py` | image |
  | Wan 2.1 Text to Video (GGUF) | `wan21_text2video_gguf.py` | video |
  | Wan 2.1 Image to Video (GGUF) | `wan21_image2video_gguf.py` | video |
  | FLUX Kontext Image Edit (Nunchaku) | `flux_kontext_nunchaku.py` | image |

  The Python samples use the original ComfyBack2Code templates in `backend\cb2c_py\templates\workflow\`.
  Deleted samples can be added again from *Workflows → Sample library*.
* **Open existing workflows** – *Workflows → Open workflow file* (or *New workflow*) accepts a ComfyUI `.json`
  (converted to Python automatically) **or an existing Python workflow `.py` script** (it must return a cb2c_py
  `Workflow`, normally from `build_workflow()`). Upload it, drop it, or type its path on this computer.
* **Wizard**
  1. *Select workflow* – the file above; the generated script is stored in `data\workflows\<id>\workflow.py`.
  2. *Models* – every model file the workflow references is detected and matched with the model table.
     URLs embedded in the workflow are picked up automatically. Each row has its own **Download** button,
     plus *Download all missing* and an *Auto-download* switch.
  3. *Run & results* – edit prompts, seed, sizes and input images, then **Run**:
     * models with a URL that are not on disk yet are **downloaded first, then the run starts by itself**;
     * models with **no URL, a wrong URL or a failed download** open the **“Models needed for this run”** dialog.
       Type a download URL **or the path of the file on this PC** (a folder works too). The model table is
       updated, and this and every later run downloads the model automatically. Local files are hard-linked
       (same drive, no extra space) or copied into the right ComfyUI models folder;
     * results open automatically in the **Image preview** or **Video preview** modal with **Download** / **Download all**.
* **Models** – grid (5 per page) of all models: edit name, download URL (or local file path), category and save
  location; add, delete, download, cancel. Downloads resume and run in the background.
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
├─ tools/                           portable Python/Git/Node downloaded by Setup.bat (only if missing)
├─ config/custom-nodes.txt          ComfyUI custom nodes installed by Setup.bat
├─ config/controlmap.json           upload / prompt / output controls and Run-time defaults
├─ scripts/setup_comfyui.py         ComfyUI + PyTorch + custom-node installer
├─ scripts/prestart.py              registers a custom MODELS_DIR with ComfyUI
├─ samples/workflows/               sample library (.json + .py workflows, library.json)
├─ samples/images, samples/videos   sample inputs / demo media
├─ backend/
│  ├─ app/                          FastAPI app (python -m app)
│  │  ├─ config.py                  .env loader/writer
│  │  ├─ events.py                  SSE event bus (download + run progress)
│  │  ├─ routers/                   system · models · workflows · runs
│  │  ├─ services/                  registry · downloader · comfy · workflows · runs
│  │  └─ defaults/models.json       initial model list
│  ├─ cb2c_py/                      workflow library (935 typed node classes, Workflow, runner, converter)
│  │  └─ templates/workflow/        Python templates used by Generate (6)
│  │  └─ templates/runner/          command-line runners for the templates (5) + input images
│  ├─ json-workflows/               input folder for the command-line JSON converter
│  ├─ tools/fake_comfyui.py         ComfyUI stand-in for tests and GPU-less demos
│  └─ tests/                        pytest suite (60 tests)
└─ frontend/                        React 18 + Vite, light theme, modal system
   └─ src/ pages · components · context · styles/theme-light.css
```

## API (backend, http://127.0.0.1:3015/docs)

`GET /api/system` · `GET /api/dashboard` · `GET|PUT /api/settings` · `POST /api/comfyui/start` ·
`POST /api/comfyui/sync-nodes` · `GET /api/events` (SSE) ·
`GET|POST /api/models` · `DELETE /api/models/{name}` · `POST /api/models/download|download-all|cancel` ·
`GET /api/workflows` · `POST /api/workflows/upload|import-path` · `GET|PATCH|DELETE /api/workflows/{id}` ·
`GET /api/workflows/{id}/script|models|parameters` · `POST /api/workflows/{id}/models/download-missing|resolve` ·
`GET|PUT /api/workflows/{id}/graph` · `GET /api/workflows/{id}/history` · `GET /api/workflows/{id}/nodes/{node}/media` ·
`GET /api/samples` · `POST /api/samples/open` ·
`GET /api/templates` · `POST /api/templates/upload` · `DELETE /api/templates/{id}` ·
`POST /api/templates/{id}/models|models/resolve|models/download-missing|generate` · `GET /api/templates/sample-images[/{name}]` ·
`POST|GET /api/runs` · `GET|DELETE /api/runs/{id}` · `POST /api/runs/{id}/cancel` ·
`GET /api/runs/{id}/files/{filename}[?download=1]` · `GET /api/runs/{id}/zip` · `POST|GET /api/uploads`

## Development

```
cd backend
.venv\Scripts\python -m pytest            # 60 tests, uses tools/fake_comfyui.py (no GPU needed)
.venv\Scripts\python -m tools.fake_comfyui --port 8188   # demo the UI without a GPU
```

## Troubleshooting

* **A download in Setup.bat fails** – check the internet connection / company proxy and run Setup.bat again;
  finished steps are skipped.
* **“ComfyUI not installed / offline”** – run `Setup.bat`, then `Start-all.bat`. The first ComfyUI start takes a minute.
* **“Connection broken: IncompleteRead” / a download stops part-way** – large model servers (e.g. the Hugging Face
  CDN) sometimes close long connections. Downloads resume automatically from the bytes already saved
  (`<model>.part`, shown as “… already downloaded”) and only stop after 6 attempts in a row without progress;
  press **Download** to continue from the same point. Permanent errors (401/403/404, a web page instead of a file)
  are not retried.
* **A download fails with 401/403** – the model is gated: add a Hugging Face token in Settings (and accept the
  licence on the model page) or a Civitai key.
* **A node shows as GenericNode / widget values look wrong** – install the custom node (add it to
  `config\custom-nodes.txt`, re-run Setup.bat), start ComfyUI, click *Sync nodes from ComfyUI*, re-import the workflow.
* **Port already in use** – change the port in `.env`, then `Stop-all.bat` and `Start-all.bat`.

---
Based on the ComfyBack2Code library (MIT). © AI Hunters Zone.

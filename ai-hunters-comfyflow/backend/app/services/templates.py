"""Python workflow templates: functions that take prompts / images / settings and return a Workflow.

Templates are read with ``ast`` (no code runs while listing). Each public function that
builds a ``Workflow`` becomes a template; its parameters become the Generate form.
An optional module-level ``TEMPLATE = {"name", "task", "description", "labels"}`` refines it.

Built-in templates: backend/cb2c_py/templates/workflow/*.py
User templates:     data/templates/*.py (uploaded from the Generate page)
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings, PROJECT_ROOT
from app.services import workflows
from cb2c_py.lib.workflow import Workflow

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "cb2c_py" / "templates" / "workflow"
SAMPLE_IMAGES = PROJECT_ROOT / "samples" / "images"

TASKS = {
    "text_to_image": "Text to Image",
    "text_to_video": "Text to Video",
    "image_to_video": "Image to Video",
    "image_edit": "Image Edit",
}

LABELS = {
    "pos_prompt": "Prompt", "positive_prompt": "Prompt", "prompt": "Prompt",
    "neg_prompt": "Negative prompt", "negative_prompt": "Negative prompt",
    "image_path": "Input image", "image_path1": "Input image", "image_path2": "Second image (optional)",
    "cfg_scale": "CFG scale", "cfg": "CFG scale", "seconds": "Duration (seconds)",
    "output_prefix": "File name prefix", "ckpt_name": "Checkpoint model", "sampler_name": "Sampler",
    "scheduler_name": "Scheduler", "steps": "Steps", "seed": "Seed", "width": "Width", "height": "Height",
}
MAIN_KINDS = ("image", "video", "prompt", "negative", "seed")


class TemplateError(ValueError):
    pass


def user_dir() -> Path:
    p = get_settings().data_dir / "templates"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ----------------------------------------------------------------- parsing
def _literal(node: Optional[ast.AST]) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


MODEL_PARAMS = {"ckpt_name", "model", "unet_name", "vae_name", "lora_name", "model_path", "model_name", "clip_name"}


def _param_kind(name: str, annotation: str, default: Any) -> str:
    n = name.lower()
    ann = annotation.lower()
    if n in MODEL_PARAMS or n.endswith("_model"):
        return "model"
    if "video" in n and ("path" in n or n == "video"):
        return "video"
    if ("image" in n and ("path" in n or n in ("image", "start_image", "input_image"))) or n in ("start_image", "init_image"):
        return "image"
    if "prompt" in n or n in ("text", "positive", "negative"):
        return "negative" if n.startswith("neg") or "negative" in n else "prompt"
    if "seed" in n:
        return "seed"
    if "bool" in ann or isinstance(default, bool):
        return "bool"
    if "float" in ann or isinstance(default, float):
        return "float"
    if re.search(r"\bint\b", ann) or isinstance(default, int):
        return "int"
    return "string"


def _builds_workflow(fn: ast.FunctionDef) -> bool:
    if fn.returns is not None and "Workflow" in ast.unparse(fn.returns):
        return True
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Workflow":
            return True
    return False


def _infer_task(stem: str, params: List[Dict[str, Any]]) -> str:
    kinds = {p["kind"] for p in params}
    names = {p["name"] for p in params}
    videoish = "video" in stem.lower() or bool(names & {"seconds", "fps", "length", "num_frames"})
    if "image" in kinds:
        return "image_to_video" if videoish else "image_edit"
    return "text_to_video" if videoish else "text_to_image"


def parse_file(path: Path, origin: str) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError) as e:
        raise TemplateError(f"{path.name}: not valid Python ({e})") from e
    meta: Dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TEMPLATE" for t in node.targets):
            meta = _literal(node.value) or {}
    module_doc = ast.get_docstring(tree) or ""
    funcs = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_") and _builds_workflow(n)
        and (not meta.get("function") or n.name == meta["function"])
    ]
    templates = []
    for fn in funcs:
        args = fn.args.args
        defaults = [None] * (len(args) - len(fn.args.defaults)) + list(fn.args.defaults)
        params = []
        for arg, default_node in zip(args, defaults):
            annotation = ast.unparse(arg.annotation) if arg.annotation is not None else ""
            default = _literal(default_node)
            required = default_node is None
            kind = _param_kind(arg.arg, annotation, default)
            label = (meta.get("labels") or {}).get(arg.arg) or LABELS.get(arg.arg) or arg.arg.replace("_", " ").capitalize()
            params.append({
                "name": arg.arg,
                "label": label,
                "kind": kind,
                "annotation": annotation,
                "default": default,
                "required": required and "Optional" not in annotation,
                "group": "main" if kind in MAIN_KINDS else "advanced",
                "choices": _choices(arg.arg),
            })
        many = len(funcs) > 1
        name = meta.get("name") if not many else f"{meta.get('name', path.stem)} · {fn.name}"
        tid = f"{origin}:{path.stem}:{fn.name}"
        task = meta.get("task") if meta.get("task") in TASKS else _infer_task(path.stem, params)
        templates.append({
            "id": tid,
            "origin": origin,
            "file": path.name,
            "path": str(path),
            "function": fn.name,
            "name": name or fn.name.replace("_", " ").title(),
            "task": task,
            "task_label": TASKS[task],
            "description": meta.get("description") or (ast.get_docstring(fn) or module_doc).strip().split("\n\n")[0],
            "params": params,
        })
    return templates


_CHOICES: Dict[str, List[str]] = {}


def _choices(name: str) -> Optional[List[str]]:
    """Known option lists for common parameters (read from the generated KSampler node)."""
    key = {"sampler_name": "sampler_name", "scheduler_name": "scheduler", "scheduler": "scheduler"}.get(name)
    if key is None:
        return None
    if key not in _CHOICES:
        try:
            from cb2c_py.nodes.generated.ksampler import KSamplerInputs

            _CHOICES[key] = list(getattr(KSamplerInputs(None), key)._type)
        except (ImportError, AttributeError, TypeError):
            _CHOICES[key] = []
    return _CHOICES[key] or None


def list_templates() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for origin, folder in (("builtin", BUILTIN_DIR), ("user", user_dir())):
        for f in sorted(folder.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                items.extend(parse_file(f, origin))
            except TemplateError:
                continue
    return items


def get(tid: str) -> Dict[str, Any]:
    if not re.fullmatch(r"(builtin|user):[A-Za-z0-9_]+:[A-Za-z0-9_]+", tid or ""):
        raise TemplateError("Invalid template id.")
    t = next((t for t in list_templates() if t["id"] == tid), None)
    if t is None:
        raise TemplateError(f"Template '{tid}' not found.")
    return t


# ----------------------------------------------------------------- upload / delete
def save_upload(raw: bytes, filename: str) -> List[Dict[str, Any]]:
    stem = re.sub(r"[^A-Za-z0-9_]", "_", Path(filename).stem).strip("_").lower() or "template"
    if not filename.lower().endswith(".py"):
        raise TemplateError("Templates are Python .py files.")
    target = user_dir() / f"{stem}.py"
    n = 2
    while target.exists():
        target = user_dir() / f"{stem}_{n}.py"
        n += 1
    target.write_bytes(raw)
    try:
        found = parse_file(target, "user")
    except TemplateError:
        target.unlink(missing_ok=True)
        raise
    if not found:
        target.unlink(missing_ok=True)
        raise TemplateError(
            "No template function found. A template is a function that builds and returns a Workflow, "
            "e.g. def my_template(prompt: str, seed: int = 0) -> Workflow."
        )
    return found


def delete(tid: str) -> None:
    t = get(tid)
    if t["origin"] != "user":
        raise TemplateError("Built-in templates cannot be deleted.")
    Path(t["path"]).unlink(missing_ok=True)


# ----------------------------------------------------------------- building
def _resolve_media(value: Any) -> Optional[str]:
    from app.services.runs import uploads_dir

    if value in (None, ""):
        return None
    if isinstance(value, dict):
        if value.get("upload"):
            p = uploads_dir() / Path(value["upload"]).name
        elif value.get("sample"):
            p = SAMPLE_IMAGES / Path(value["sample"]).name
        else:
            return None
        if not p.is_file():
            raise TemplateError(f"Input file '{p.name}' is missing; choose the image again.")
        return str(p)
    return str(value)


def _coerce(param: Dict[str, Any], value: Any, placeholder: bool) -> Any:
    kind = param["kind"]
    if kind in ("image", "video"):
        v = _resolve_media(value)
        if v is None and param["required"]:
            if placeholder:
                return str(SAMPLE_IMAGES / "girl.png")
            raise TemplateError(f"Please choose the {param['label'].lower()}.")
        return v
    if value is None or value == "":
        if param["required"]:
            if placeholder:
                return {"prompt": "placeholder", "negative": "", "seed": 0, "int": 0, "float": 0.0, "bool": False}.get(kind, "")
            if kind == "negative":
                return ""
            raise TemplateError(f"Please fill in “{param['label']}”.")
        return param["default"]
    try:
        if kind in ("int", "seed"):
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "bool":
            return bool(value)
    except (TypeError, ValueError) as e:
        raise TemplateError(f"“{param['label']}” must be a number.") from e
    return value


def build(tid: str, values: Dict[str, Any], placeholder: bool = False) -> Workflow:
    """Calls the template function. ``placeholder`` fills required inputs for model detection."""
    t = get(tid)
    kwargs = {p["name"]: _coerce(p, (values or {}).get(p["name"]), placeholder) for p in t["params"]}
    mod_name = f"comfyflow_tpl_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(mod_name, t["path"])
    if spec is None or spec.loader is None:
        raise TemplateError("Cannot load the template file.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        wf = getattr(module, t["function"])(**kwargs)
    except TemplateError:
        raise
    except Exception as e:  # noqa: BLE001 - user template code
        raise TemplateError(f"The template failed to build: {type(e).__name__}: {e}") from e
    finally:
        sys.modules.pop(mod_name, None)
    if not isinstance(wf, Workflow):
        raise TemplateError(f"{t['function']}() must return a cb2c_py Workflow.")
    return wf


def detect_models(tid: str, values: Optional[Dict[str, Any]] = None, register: bool = True) -> List[Dict[str, Any]]:
    """Models the template needs for these values (e.g. the chosen checkpoint)."""
    wf = build(tid, values or {}, placeholder=True)
    return workflows.detect_models_in_prompt(wf.to_prompt(), None, register)


def resolve_models(tid: str, values: Dict[str, Any], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        workflows.resolve_rows(detect_models(tid, values), items)
    except workflows.WorkflowError as e:
        raise TemplateError(str(e)) from e
    return detect_models(tid, values)

"""Workflow Editor: graph view of a workflow, field controls, save back to workflow.py, Run-time fields."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings, PROJECT_ROOT
from app.services import comfy, controlmap, workflows
from app.services.workflows import WorkflowError, _atomic_write
from cb2c_py.tools.convert_workflow import generate_script, sanitize_name, NodeCatalog

UPLOAD_CONTROLS = {"upload_image": "image", "upload_video": "video", "upload_audio": "audio"}
KIND_BY_CONTROL = {
    "prompt": "text", "text": "text", "upload_image": "image", "upload_video": "video", "upload_audio": "audio",
    "seed": "seed", "number": "number", "select": "select", "toggle": "bool", "string": "string",
}


def _folder(wid: str) -> Path:
    return workflows._root() / wid


def _editor_path(wid: str) -> Path:
    return _folder(wid) / "editor.json"


def read_editor(wid: str) -> Dict[str, Any]:
    p = _editor_path(wid)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for key in ("positions", "fields", "outputs"):
        data.setdefault(key, {})
    return data


def _is_link(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)) and isinstance(v[1], int) and not isinstance(v[1], bool)


def _pretty(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _auto_control(name: str, itype: Any, opts: Dict[str, Any], value: Any) -> str:
    if isinstance(itype, list):
        return "select"
    t = str(itype).upper()
    if t == "COMBO":
        return "select"
    if t == "BOOLEAN" or isinstance(value, bool):
        return "toggle"
    if t in ("INT", "FLOAT") or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return "seed" if name in ("seed", "noise_seed") else "number"
    if t == "STRING" or isinstance(value, str):
        return "text" if opts.get("multiline") else "string"
    return "string"


def _field(ct: str, title: str, name: str, itype: Any, opts: Dict[str, Any], value: Any, override: Dict[str, Any]) -> Dict[str, Any]:
    rule = controlmap.field_rule(ct, name, itype, opts)
    control = rule.get("control") or _auto_control(name, itype, opts, value)
    options = itype if isinstance(itype, list) else opts.get("options") if isinstance(opts.get("options"), list) else None
    if control == "select" and not options:
        control = "string"
    runtime_default = bool(rule.get("runtime", False))
    default_label = rule.get("label") or (title if control == "prompt" and title.lower() != ct.lower() else f"{title} · {_pretty(name)}" if control == "prompt" else _pretty(name))
    is_float = str(itype).upper() == "FLOAT" or isinstance(value, float)
    return {
        "name": name,
        "control": control,
        "type": "COMBO" if isinstance(itype, list) else str(itype),
        "value": value,
        "options": options,
        "min": opts.get("min"),
        "max": opts.get("max"),
        "step": opts.get("step") or (None if is_float else 1),
        "is_float": is_float,
        "multiline": bool(opts.get("multiline")) or control in ("prompt", "text"),
        "tooltip": opts.get("tooltip"),
        "runtime_default": runtime_default,
        "runtime": bool(override["runtime"]) if "runtime" in override else runtime_default,
        "label": override.get("label") or default_label,
        "default_label": default_label,
    }


def _media_kind(value: Any) -> Optional[str]:
    return None if not isinstance(value, str) else {".mp4": "video", ".webm": "video", ".mov": "video", ".mkv": "video",
                                                     ".avi": "video", ".wav": "audio", ".mp3": "audio", ".flac": "audio",
                                                     ".ogg": "audio", ".m4a": "audio"}.get(Path(value).suffix.lower(), "image")


def build_graph(wid: str) -> Dict[str, Any]:
    meta = workflows.get(wid)
    prompt = workflows._prompt(wid)
    editor = read_editor(wid)
    cat: NodeCatalog = comfy.catalog()

    # model readiness per node
    model_state: Dict[str, List[Dict[str, Any]]] = {}
    for m in workflows.detect_models(wid, register=False):
        for used in m.get("used_by", []):
            nid = used.rsplit("(", 1)[-1].rstrip(")")
            model_state.setdefault(nid, []).append({"name": m["name"], "status": m["status"]})

    # last outputs per node
    from app.services.runs import runs

    last_outputs: Dict[str, List[Dict[str, Any]]] = {}
    for r in runs.list(wid):  # newest first: keep each node's outputs from its latest successful run
        if r.get("status") != "succeeded":
            continue
        per_node: Dict[str, List[Dict[str, Any]]] = {}
        for o in r.get("outputs", []):
            per_node.setdefault(str(o.get("node_id")), []).append({"run_id": r["id"], "filename": o["filename"], "kind": o["kind"]})
        for nid, outs in per_node.items():
            last_outputs.setdefault(nid, outs)

    from app.services.registry import registry

    registry_models = registry.all()
    feeds: Dict[str, set] = {}  # node id -> names of the inputs it is connected to downstream
    for node in prompt.values():
        for name, value in node["inputs"].items():
            if _is_link(value):
                feeds.setdefault(str(value[0]), set()).add(name)

    nodes, edges = [], []
    for nid, node in prompt.items():
        ct = node["class_type"]
        spec = cat.spec(ct)
        title = (node.get("_meta") or {}).get("title") or (spec or {}).get("display_name") or ct
        if title == ct and controlmap.node_info(ct)["role"] == "prompt":
            if "positive" in feeds.get(nid, set()):
                title = "Positive Prompt"
            elif "negative" in feeds.get(nid, set()):
                title = "Negative Prompt"
        info = controlmap.node_info(ct)
        overrides = editor["fields"].get(nid, {})
        fields, connections, seen = [], [], set()
        spec_inputs = (spec or {}).get("inputs") or []
        for entry in spec_inputs:
            name = entry["name"]
            seen.add(name)
            value = node["inputs"].get(name)
            if _is_link(value):
                connections.append({"input": name, "from": str(value[0]), "slot": value[1]})
                continue
            if not NodeCatalog.is_widget(entry):
                continue  # an unconnected socket (optional input)
            fields.append(_field(ct, title, name, entry["type"], entry.get("opts") or {}, value, overrides.get(name, {})))
        for name, value in node["inputs"].items():
            if name in seen:
                continue
            if _is_link(value):
                connections.append({"input": name, "from": str(value[0]), "slot": value[1]})
            else:
                fields.append(_field(ct, title, name, "", {}, value, overrides.get(name, {})))
        for c in connections:
            src = prompt.get(c["from"], {})
            src_spec = cat.spec(src.get("class_type", "")) or {}
            outs = src_spec.get("outputs") or []
            dtype = outs[c["slot"]]["type"] if c["slot"] < len(outs) else "*"
            edges.append({
                "id": f"{c['from']}:{c['slot']}->{nid}:{c['input']}",
                "source": c["from"], "target": nid, "slot": c["slot"], "input": c["input"],
                "type": dtype if isinstance(dtype, str) else "COMBO",
                "label": outs[c["slot"]]["name"] if c["slot"] < len(outs) else f"output {c['slot']}",
            })
        for f in fields:  # dropdowns always include the current value; model inputs list the model table too
            if f["control"] != "select":
                continue
            opts = list(f["options"] or [])
            category = workflows.INPUT_CATEGORY.get(f["name"])
            if category:
                allowed = {category} | ({"unet", "diffusion_models"} if category in ("unet", "diffusion_models") else set())
                opts += [m["name"] for m in registry_models if m.get("category") in allowed]
            if f["value"] not in (None, "") and f["value"] not in opts:
                opts.insert(0, f["value"])
            f["options"] = list(dict.fromkeys(opts))
        summary_keys = info.get("summary") or [f["name"] for f in fields if f["control"] in ("number", "select", "seed")][:3]
        by_name = {f["name"]: f for f in fields}
        summary = " · ".join(str(by_name[k]["value"]) for k in summary_keys if k in by_name and by_name[k]["value"] not in (None, ""))
        prompt_field = next((f for f in fields if f["control"] == "prompt" and f["value"]), None)
        upload_field = next((f for f in fields if f["control"] in UPLOAD_CONTROLS), None)
        preview = None
        if upload_field and upload_field["value"]:
            preview = {"kind": UPLOAD_CONTROLS[upload_field["control"]], "url": f"/api/workflows/{wid}/nodes/{nid}/media?input={upload_field['name']}",
                       "name": Path(str(upload_field["value"])).name}
        output_type = editor["outputs"].get(nid, info.get("output")) if info["role"] == "output" else None
        results = last_outputs.get(nid, [])
        nodes.append({
            "id": nid,
            "class_type": ct,
            "title": title,
            "role": info["role"],
            "icon": info.get("icon"),
            "output": output_type,
            "summary": summary or (str(prompt_field["value"])[:80] if prompt_field else ""),
            "summary_keys": [k for k in summary_keys if k in by_name],
            "fields": fields,
            "connections": connections,
            "runtime_count": sum(1 for f in fields if f["runtime"]),
            "models": model_state.get(nid, []),
            "preview": preview,
            "results": [
                {**r, "url": f"/api/runs/{r['run_id']}/files/{r['filename']}"} for r in results
            ],
            "known": spec is not None,
            "position": editor["positions"].get(nid),
        })
    return {
        "workflow": meta,
        "nodes": nodes,
        "edges": edges,
        "view": editor.get("view", "simple"),
        "saved_at": editor.get("saved_at"),
    }


# ----------------------------------------------------------------- saving
def _coerce(field: Dict[str, Any], value: Any) -> Any:
    from app.services.runs import uploads_dir

    if isinstance(value, dict) and value.get("upload"):
        p = uploads_dir() / Path(value["upload"]).name
        if not p.is_file():
            raise WorkflowError(f"Uploaded file '{value['upload']}' is missing; upload it again.")
        return str(p)
    if field["control"] in ("number", "seed"):
        if value in ("", None):
            raise WorkflowError(f"“{field['label']}” needs a number.")
        try:
            num = float(value) if field["is_float"] else int(value)
        except (TypeError, ValueError) as e:
            raise WorkflowError(f"“{field['label']}” must be a number.") from e
        if field.get("min") is not None and num < field["min"]:
            raise WorkflowError(f"“{field['label']}” must be at least {field['min']}.")
        if field.get("max") is not None and num > field["max"]:
            raise WorkflowError(f"“{field['label']}” must be at most {field['max']}.")
        return num
    if field["control"] == "toggle":
        return bool(value)
    if field["control"] == "select" and field.get("options") and value not in field["options"]:
        raise WorkflowError(f"“{value}” is not a valid choice for {field['label']}.")
    return value


def save_graph(wid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Applies editor changes: values into workflow.py (with a backup), run-time/labels/positions into editor.json."""
    graph = build_graph(wid)
    by_id = {n["id"]: n for n in graph["nodes"]}
    prompt = copy.deepcopy(workflows._prompt(wid))
    changed = False
    for nid, values in (body.get("values") or {}).items():
        node = by_id.get(str(nid))
        if node is None:
            raise WorkflowError(f"Node {nid} does not exist in this workflow.")
        fields = {f["name"]: f for f in node["fields"]}
        for name, value in values.items():
            if name not in fields:
                raise WorkflowError(f"“{name}” of {node['title']} cannot be edited (it is connected to another node).")
            new = _coerce(fields[name], value)
            if prompt[str(nid)]["inputs"].get(name) != new:
                prompt[str(nid)]["inputs"][name] = new
                changed = True

    folder = _folder(wid)
    if changed:
        meta = workflows._read_meta(wid)
        history = folder / "history"
        history.mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copyfile(folder / "workflow.py", history / f"workflow_{stamp}.py")
        titles = {nid: (n.get("_meta") or {}).get("title") for nid, n in prompt.items() if (n.get("_meta") or {}).get("title")}
        script, _ = generate_script(prompt, sanitize_name(wid), meta.get("source_filename", "workflow"), comfy.catalog(),
                                    titles, meta.get("notes"))
        _atomic_write(folder / "workflow.py", script)
        _atomic_write(folder / "prompt.json", json.dumps(prompt, indent=2))
        meta["edited_at"] = workflows._now()
        workflows._write_meta(wid, meta)

    editor = read_editor(wid)
    for nid, fields in (body.get("fields") or {}).items():
        target = editor["fields"].setdefault(str(nid), {})
        for name, cfg in fields.items():
            entry = target.setdefault(name, {})
            if "runtime" in cfg:
                entry["runtime"] = bool(cfg["runtime"])
            if "label" in cfg:
                label = str(cfg["label"] or "").strip()
                if label:
                    entry["label"] = label
                else:
                    entry.pop("label", None)
    for nid, out in (body.get("outputs") or {}).items():
        if out not in ("image", "video", "audio"):
            raise WorkflowError("Expected output must be image, video or audio.")
        editor["outputs"][str(nid)] = out
    for nid, pos in (body.get("positions") or {}).items():
        if isinstance(pos, dict) and isinstance(pos.get("x"), (int, float)) and isinstance(pos.get("y"), (int, float)):
            editor["positions"][str(nid)] = {"x": round(pos["x"], 1), "y": round(pos["y"], 1)}
    if body.get("reset_positions"):
        editor["positions"] = {}
    if body.get("view") in ("simple", "detailed"):
        editor["view"] = body["view"]
    editor["saved_at"] = workflows._now()
    _atomic_write(_editor_path(wid), json.dumps(editor, indent=2))
    return build_graph(wid)


def history(wid: str) -> List[Dict[str, Any]]:
    folder = _folder(wid) / "history"
    if not folder.exists():
        return []
    return [{"file": p.name, "saved": p.stat().st_mtime} for p in sorted(folder.glob("workflow_*.py"), reverse=True)]


# ----------------------------------------------------------------- run screen
def runtime_parameters(wid: str) -> Dict[str, Any]:
    """Run-time fields (from the control map + editor ticks) and the expected outputs."""
    graph = build_graph(wid)
    params, outputs = [], []
    order = {"image": 0, "video": 0, "audio": 0, "text": 1, "seed": 2}
    for n in graph["nodes"]:
        if n["role"] == "output" and n.get("output"):
            outputs.append({"node_id": n["id"], "title": n["title"], "type": n["output"]})
        for f in n["fields"]:
            if not f["runtime"]:
                continue
            params.append({
                "node_id": n["id"],
                "class_type": n["class_type"],
                "title": n["title"],
                "input": f["name"],
                "label": f["label"],
                "kind": KIND_BY_CONTROL.get(f["control"], "string"),
                "value": f["value"],
                "options": f["options"],
                "min": f["min"],
                "max": f["max"],
                "step": f["step"],
                "is_float": f["is_float"],
                "tooltip": f["tooltip"],
                "preview": n["preview"] if f["control"] in UPLOAD_CONTROLS else None,
            })

    def rank(p):
        t = f"{p['label']} {p['title']} {p['input']}".lower()
        return (order.get(p["kind"], 3), 2 if "neg" in t else 0 if "pos" in t else 1, p["label"])

    params.sort(key=rank)
    return {"parameters": params, "outputs": outputs}


# ----------------------------------------------------------------- node media
def node_media_path(wid: str, nid: str, input_name: str) -> Path:
    """The file currently set on an upload input (for previews)."""
    prompt = workflows._prompt(wid)
    node = prompt.get(str(nid))
    if node is None:
        raise WorkflowError(f"Node {nid} not found.")
    value = node["inputs"].get(input_name)
    if not isinstance(value, str) or not value:
        raise WorkflowError("This input has no file.")
    s = get_settings()
    candidates = []
    p = Path(value)
    if p.is_absolute():
        candidates.append(p)
    candidates += [s.comfyui_dir / "input" / value, PROJECT_ROOT / "samples" / "images" / Path(value).name]
    allowed = [s.data_dir.resolve(), PROJECT_ROOT.resolve(), s.comfyui_dir.resolve()]
    for c in candidates:
        try:
            rc = c.resolve()
        except OSError:
            continue
        if rc.is_file() and any(rc.is_relative_to(a) for a in allowed):
            return rc
    raise WorkflowError(f"'{value}' is not on this computer (it may exist only in ComfyUI's input folder).")


# ----------------------------------------------------------------- live run view
def _light_graph(prompt: Dict[str, Any]) -> Dict[str, Any]:
    """Nodes + typed edges of any API prompt (used for template runs, which have no editor)."""
    cat: NodeCatalog = comfy.catalog()
    feeds: Dict[str, set] = {}
    for node in prompt.values():
        for name, value in node["inputs"].items():
            if _is_link(value):
                feeds.setdefault(str(value[0]), set()).add(name)
    nodes, edges = [], []
    for nid, node in prompt.items():
        ct = node["class_type"]
        spec = cat.spec(ct)
        info = controlmap.node_info(ct)
        title = (node.get("_meta") or {}).get("title") or (spec or {}).get("display_name") or ct
        if title == ct and info["role"] == "prompt":
            title = "Positive Prompt" if "positive" in feeds.get(nid, set()) else "Negative Prompt" if "negative" in feeds.get(nid, set()) else title
        summary = ""
        for name, value in node["inputs"].items():
            if _is_link(value):
                src = prompt.get(str(value[0]), {})
                outs = (cat.spec(src.get("class_type", "")) or {}).get("outputs") or []
                dtype = outs[value[1]]["type"] if value[1] < len(outs) else "*"
                edges.append({
                    "id": f"{value[0]}:{value[1]}->{nid}:{name}", "source": str(value[0]), "target": nid,
                    "slot": value[1], "input": name, "type": dtype if isinstance(dtype, str) else "COMBO",
                })
            elif not summary and isinstance(value, str) and value and (info["role"] in ("prompt", "model", "input") or name in ("text", "prompt")):
                summary = Path(value).name if info["role"] in ("model", "input") else value[:90]
        nodes.append({
            "id": nid, "class_type": ct, "title": title, "role": info["role"], "icon": info.get("icon"),
            "output": info.get("output") if info["role"] == "output" else None, "summary": summary,
            "fields": [], "results": [], "models": [], "known": spec is not None, "position": None,
        })
    return {"nodes": nodes, "edges": edges}


def run_graph(run: Dict[str, Any]) -> Dict[str, Any]:
    """The graph a run executes, for the live node-by-node progress view."""
    if run.get("template_id"):
        from app.services import templates

        wf = templates.build(run["template_id"], run.get("template_values") or {}, placeholder=True)
        g = _light_graph(wf.to_prompt())
    else:
        full = build_graph(run["workflow_id"])
        g = {"nodes": [{**n, "results": []} for n in full["nodes"]], "edges": full["edges"]}
    return {"run_id": run["id"], "name": run.get("workflow_name"), **g}

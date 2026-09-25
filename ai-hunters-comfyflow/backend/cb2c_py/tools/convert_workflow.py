# AI Hunters ComfyFlow - cb2c_py/tools/convert_workflow.py
"""Convert ComfyUI workflow JSON (UI "graph" format or API "prompt" format)
into a runnable Python script built on cb2c_py.

Programmatic use::

    from cb2c_py.tools.convert_workflow import convert, NodeCatalog
    result = convert(json.load(open("wf.json")), name="my_wf", catalog=NodeCatalog())
    open("my_wf.py", "w").write(result.script)

CLI (converts every json-workflows/*.json into user/workflows/*.py)::

    python -m cb2c_py.tools.convert_workflow [-o OUTPUT_DIR] [--object-info object_info.json]
"""

import argparse
import datetime as _dt
import importlib
import importlib.util
import inspect
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
CONTROL_VALUES = {"fixed", "increment", "decrement", "randomize"}
SEED_NAMES = {"seed", "noise_seed"}
NOTE_TYPES = {"Note", "MarkdownNote"}
VIRTUAL_TYPES = {"Reroute", "PrimitiveNode"} | NOTE_TYPES
MODE_MUTED = 2
MODE_BYPASS = 4


def sanitize_name(name: str) -> str:
    """Converts a name into a valid Python identifier (same rule as the node generator)."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(name))
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized
    return sanitized or "_"


# Backwards compatible alias
sanitize_class_name = sanitize_name


# --------------------------------------------------------------------------- catalog
class NodeCatalog:
    """Knows the ordered inputs/outputs of node types.

    Uses ComfyUI's ``/object_info`` data when available (most accurate) and the
    generated ``cb2c_py.nodes.generated`` wrappers as a fallback.
    """

    def __init__(self, object_info: Optional[Dict[str, Any]] = None):
        self.object_info = object_info or {}
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._wrappers: Dict[str, Any] = {}

    # -- wrappers --------------------------------------------------------
    def wrapper_class(self, class_type: str):
        """Returns the generated wrapper class for ``class_type`` or None."""
        if class_type in self._wrappers:
            return self._wrappers[class_type]
        cls = None
        py_name = sanitize_name(class_type)
        module_name = f"cb2c_py.nodes.generated.{py_name.lower()}"
        try:
            if importlib.util.find_spec(module_name) is not None:
                module = importlib.import_module(module_name)
                cls = getattr(module, py_name, None)
        except (ImportError, ValueError):
            cls = None
        self._wrappers[class_type] = cls
        return cls

    def wrapper_output_attrs(self, class_type: str) -> List[str]:
        cls = self.wrapper_class(class_type)
        if cls is None:
            return []
        module = importlib.import_module(cls.__module__)
        outputs_cls = getattr(module, f"{cls.__name__}Outputs", None)
        if outputs_cls is None:
            return []
        return list(vars(outputs_cls(None)).keys())

    # -- specs -----------------------------------------------------------
    def spec(self, class_type: str) -> Optional[Dict[str, Any]]:
        if class_type not in self._cache:
            self._cache[class_type] = self._spec_from_object_info(class_type) or self._spec_from_wrapper(class_type)
        return self._cache[class_type]

    def _spec_from_object_info(self, class_type: str) -> Optional[Dict[str, Any]]:
        details = self.object_info.get(class_type)
        if not details:
            return None
        inputs: List[Dict[str, Any]] = []
        order = details.get("input_order") or {}
        for group in ("required", "optional"):
            group_data = (details.get("input") or {}).get(group) or {}
            names = order.get(group) or list(group_data.keys())
            for name in names:
                if name not in group_data:
                    continue
                config = group_data[name]
                if not isinstance(config, (list, tuple)) or not config:
                    continue
                opts = config[1] if len(config) > 1 and isinstance(config[1], dict) else {}
                inputs.append({"name": name, "type": config[0], "opts": opts, "optional": group == "optional"})
        outputs = [
            {"name": n, "type": t}
            for n, t in zip(details.get("output_name") or details.get("output") or [], details.get("output") or [])
        ]
        return {"inputs": inputs, "outputs": outputs, "display_name": details.get("display_name", class_type)}

    def _spec_from_wrapper(self, class_type: str) -> Optional[Dict[str, Any]]:
        cls = self.wrapper_class(class_type)
        if cls is None:
            return None
        module = importlib.import_module(cls.__module__)
        inputs_cls = getattr(module, f"{cls.__name__}Inputs", None)
        outputs_cls = getattr(module, f"{cls.__name__}Outputs", None)
        params = inspect.signature(cls.__init__).parameters
        inputs = []
        if inputs_cls is not None:
            for slot in vars(inputs_cls(None)).values():
                p = params.get(slot._name)
                optional = p is not None and p.default is None
                inputs.append({"name": slot._name, "type": slot._type, "opts": {}, "optional": optional})
        outputs = []
        if outputs_cls is not None:
            outputs = [{"name": s._name, "type": s._type} for s in vars(outputs_cls(None)).values()]
        return {"inputs": inputs, "outputs": outputs, "display_name": class_type}

    @staticmethod
    def is_widget(entry: Dict[str, Any]) -> bool:
        if (entry.get("opts") or {}).get("forceInput"):
            return False
        t = entry.get("type")
        return isinstance(t, list) or (isinstance(t, str) and t in WIDGET_TYPES)

    def widget_inputs(self, class_type: str) -> Optional[List[Dict[str, Any]]]:
        spec = self.spec(class_type)
        if spec is None:
            return None
        return [e for e in spec["inputs"] if self.is_widget(e)]


# --------------------------------------------------------------------------- result
@dataclass
class ConversionResult:
    script: str
    prompt: Dict[str, Any]
    format: str
    node_count: int
    titles: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    model_hints: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- UI -> API
def _links_by_id(ui: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    links: Dict[int, Dict[str, Any]] = {}
    for link in ui.get("links") or []:
        if isinstance(link, dict):
            links[int(link["id"])] = {
                "from": str(link.get("origin_id")),
                "from_slot": int(link.get("origin_slot", 0)),
                "to": str(link.get("target_id")),
                "type": link.get("type"),
            }
        elif isinstance(link, (list, tuple)) and len(link) >= 5:
            links[int(link[0])] = {
                "from": str(link[1]),
                "from_slot": int(link[2]),
                "to": str(link[3]),
                "type": link[5] if len(link) > 5 else None,
            }
    return links


def detect_format(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Returns ``("ui"|"api", payload)`` or raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("The file does not contain a ComfyUI workflow object.")
    if isinstance(data.get("nodes"), list):
        return "ui", data
    if isinstance(data.get("prompt"), dict):
        return detect_format(data["prompt"])
    if isinstance(data.get("workflow"), dict) and isinstance(data["workflow"].get("nodes"), list):
        return "ui", data["workflow"]
    if data and all(isinstance(v, dict) and "class_type" in v for v in data.values()):
        return "api", data
    raise ValueError(
        "This JSON is not a ComfyUI workflow (expected a UI export with 'nodes' "
        "or an API export with 'class_type' entries)."
    )


def ui_to_api(ui: Dict[str, Any], catalog: NodeCatalog):
    """Converts a UI-format workflow into API format.

    Returns ``(prompt, titles, notes, model_hints, warnings)``.
    """
    warnings: List[str] = []
    notes: List[str] = []
    titles: Dict[str, str] = {}
    model_hints: List[Dict[str, str]] = []
    nodes = {str(n["id"]): n for n in ui.get("nodes", []) if "id" in n}
    links = _links_by_id(ui)
    subgraph_ids = {
        sg.get("id") for sg in ((ui.get("definitions") or {}).get("subgraphs") or []) if isinstance(sg, dict)
    }

    for model in ui.get("models") or []:
        if isinstance(model, dict) and model.get("name"):
            model_hints.append(model)

    def resolve(link_id: Optional[int], depth: int = 0):
        """Follows a link through virtual/bypassed nodes: ('link', id, slot) | ('value', v) | None."""
        if link_id is None or depth > 64:
            return None
        link = links.get(int(link_id))
        if link is None:
            return None
        src = nodes.get(link["from"])
        if src is None:
            return None
        stype = src.get("type")
        mode = src.get("mode", 0)
        if stype == "Reroute":
            src_inputs = src.get("inputs") or []
            return resolve(src_inputs[0].get("link") if src_inputs else None, depth + 1)
        if stype == "PrimitiveNode":
            wv = src.get("widgets_values") or []
            return ("value", wv[0]) if wv else None
        if mode == MODE_MUTED:
            return None
        if mode == MODE_BYPASS:
            ltype = link.get("type")
            candidates = [i for i in (src.get("inputs") or []) if i.get("link") is not None]
            for inp in candidates:
                if ltype and inp.get("type") == ltype:
                    return resolve(inp.get("link"), depth + 1)
            if len(candidates) == 1:
                return resolve(candidates[0].get("link"), depth + 1)
            return None
        return ("link", link["from"], link["from_slot"])

    prompt: Dict[str, Any] = {}
    for node_id, node in nodes.items():
        ctype = node.get("type")
        mode = node.get("mode", 0)
        props = node.get("properties") or {}
        for m in props.get("models") or []:
            if isinstance(m, dict) and m.get("name"):
                model_hints.append(m)
        if not ctype:
            continue
        if ctype in NOTE_TYPES:
            wv = node.get("widgets_values") or [""]
            if wv and isinstance(wv[0], str) and wv[0].strip():
                notes.append(wv[0].strip())
            continue
        if ctype in VIRTUAL_TYPES or mode in (MODE_MUTED, MODE_BYPASS):
            continue
        if ctype in subgraph_ids:
            warnings.append(f"Node {node_id} is a subgraph; subgraphs are not supported yet and were skipped.")
            continue

        inputs: Dict[str, Any] = {}
        # Widget values
        wv = node.get("widgets_values")
        widget_entries = catalog.widget_inputs(ctype)
        if isinstance(wv, dict):
            known = {e["name"] for e in widget_entries} if widget_entries is not None else None
            for k, v in wv.items():
                if known is None or k in known:
                    inputs[k] = v
        elif isinstance(wv, list) and wv:
            if widget_entries is None:
                names = [i["name"] for i in (node.get("inputs") or []) if "widget" in i]
                if names:
                    warnings.append(
                        f"Node '{ctype}' ({node_id}) is unknown to the node catalog; widget values were "
                        "mapped by position. Sync nodes from ComfyUI and re-import for exact mapping."
                    )
                    widget_entries = [{"name": n, "type": "", "opts": {}} for n in names]
                else:
                    warnings.append(
                        f"Node '{ctype}' ({node_id}) is unknown to the node catalog; its widget values "
                        "could not be mapped. Install the custom node, sync nodes and re-import."
                    )
                    widget_entries = []
            i = 0
            for entry in widget_entries:
                if i >= len(wv):
                    break
                inputs[entry["name"]] = wv[i]
                i += 1
                wants_control = (entry.get("opts") or {}).get("control_after_generate") or (
                    entry.get("type") == "INT" and entry["name"] in SEED_NAMES
                )
                if wants_control and i < len(wv) and isinstance(wv[i], str) and wv[i] in CONTROL_VALUES:
                    i += 1
        # Linked inputs (override widget values that were converted to sockets)
        for inp in node.get("inputs") or []:
            if inp.get("link") is None:
                continue
            resolved = resolve(inp["link"])
            name = inp.get("name")
            if resolved is None:
                continue  # broken/muted source: keep the widget value if there is one
            if resolved[0] == "value":
                inputs[name] = resolved[1]
            else:
                inputs[name] = [resolved[1], resolved[2]]
        entry = {"inputs": inputs, "class_type": ctype}
        if node.get("title") and node["title"] != ctype:
            titles[node_id] = node["title"]
            entry["_meta"] = {"title": node["title"]}
        prompt[node_id] = entry

    # Drop links that point at nodes that were skipped
    for node_id, entry in prompt.items():
        for name, value in list(entry["inputs"].items()):
            if _is_link(value) and str(value[0]) not in prompt:
                del entry["inputs"][name]
                warnings.append(f"Input '{name}' of node {node_id} pointed at a skipped node and was removed.")
    return prompt, titles, notes, model_hints, warnings


def _is_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and not isinstance(value[0], bool)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    )


def _sort_key(node_id: str):
    return (0, int(node_id), "") if str(node_id).isdigit() else (1, 0, str(node_id))


def topo_sort(prompt: Dict[str, Any]) -> List[str]:
    ids = sorted(prompt.keys(), key=_sort_key)
    deps = {nid: set() for nid in ids}
    for nid in ids:
        for v in prompt[nid]["inputs"].values():
            if _is_link(v) and str(v[0]) in deps:
                deps[nid].add(str(v[0]))
    ordered, done = [], set()
    while len(ordered) < len(ids):
        progress = False
        for nid in ids:
            if nid not in done and deps[nid] <= done:
                ordered.append(nid)
                done.add(nid)
                progress = True
        if not progress:  # cycle: append the rest in id order
            ordered.extend(n for n in ids if n not in done)
            break
    return ordered


# --------------------------------------------------------------------------- codegen
def generate_script(
    prompt: Dict[str, Any],
    name: str,
    source_filename: str,
    catalog: NodeCatalog,
    titles: Optional[Dict[str, str]] = None,
    notes: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """Returns ``(python_source, warnings)``."""
    warnings: List[str] = []
    titles = titles or {}
    order = topo_sort(prompt)
    var_names: Dict[str, str] = {}
    used = set()
    for nid in order:
        base = f"{sanitize_name(prompt[nid]['class_type']).lower()}_{sanitize_name(nid).lstrip('_')}"
        var = base
        n = 2
        while var in used:
            var = f"{base}_{n}"
            n += 1
        used.add(var)
        var_names[nid] = var

    imports = set()
    needs_generic = False
    body: List[str] = []

    def link_expr(value) -> str:
        src_id, slot = str(value[0]), int(value[1])
        src_var = var_names[src_id]
        src_type = prompt[src_id]["class_type"]
        attrs = catalog.wrapper_output_attrs(src_type)
        if slot < len(attrs):
            return f"{src_var}.outputs.{attrs[slot]}"
        return f"{src_var}.output({slot})"

    def value_expr(value) -> str:
        if _is_link(value) and str(value[0]) in var_names:
            return link_expr(value)
        return repr(value)

    for nid in order:
        node = prompt[nid]
        ctype = node["class_type"]
        var = var_names[nid]
        title = titles.get(nid) or (node.get("_meta") or {}).get("title")
        comment = f"    # [{nid}] {ctype}" + (f" - {title}" if title and title != ctype else "")
        body.append(comment)
        cls = catalog.wrapper_class(ctype)
        extras: List[Tuple[str, str]] = []
        if cls is not None:
            imports.add(f"from {cls.__module__} import {cls.__name__}")
            params = inspect.signature(cls.__init__).parameters
            kwargs: List[Tuple[str, str]] = []
            given = set()
            for in_name, value in node["inputs"].items():
                s_name = sanitize_name(in_name)
                if s_name in params and s_name != "self":
                    kwargs.append((s_name, value_expr(value)))
                    given.add(s_name)
                else:
                    extras.append((in_name, value_expr(value)))
            for p in params.values():
                if p.name == "self" or p.name in given:
                    continue
                if p.default is inspect.Parameter.empty and p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                    kwargs.append((p.name, "None  # TODO: required input missing in the source workflow"))
                    warnings.append(f"Node {ctype} ({nid}) is missing required input '{p.name}'.")
            if kwargs:
                body.append(f"    {var} = wf.add_node(")
                body.append(f"        {cls.__name__}(")
                for k, v in kwargs:
                    if "  # " in v:
                        code, cmt = v.split("  # ", 1)
                        body.append(f"            {k}={code},  # {cmt}")
                    else:
                        body.append(f"            {k}={v},")
                body.append("        ),")
                body.append(f"        node_id={nid!r},")
                body.append("    )")
            else:
                body.append(f"    {var} = wf.add_node({cls.__name__}(), node_id={nid!r})")
        else:
            needs_generic = True
            warnings.append(
                f"'{ctype}' has no generated wrapper; using GenericNode (sync nodes from ComfyUI for typed code)."
            )
            if node["inputs"]:
                body.append(f"    {var} = wf.add_node(")
                body.append(f"        GenericNode({ctype!r}, {{")
                for k, v in node["inputs"].items():
                    body.append(f"            {k!r}: {value_expr(v)},")
                body.append("        }),")
                body.append(f"        node_id={nid!r},")
                body.append("    )")
            else:
                body.append(f"    {var} = wf.add_node(GenericNode({ctype!r}), node_id={nid!r})")
        for k, v in extras:
            body.append(f"    {var}.set_input({k!r}, {v})")
        if title and title != ctype:
            body.append(f"    {var}.title = {title!r}")
        body.append("")

    header = [
        '"""',
        "AI Hunters ComfyFlow - auto-generated workflow script.",
        f"Source: {source_filename}",
        f"Converted: {_dt.datetime.now().isoformat(timespec='seconds')}  |  Nodes: {len(prompt)}",
        "",
        "build_workflow() must return a cb2c_py Workflow; you may edit this file freely.",
        '"""',
        "",
    ]
    lines = header + ["from cb2c_py.lib.workflow import Workflow"]
    if needs_generic:
        lines.append("from cb2c_py.nodes.base_node import GenericNode")
    lines += sorted(imports)
    lines += ["", f"WORKFLOW_NAME = {name!r}", ""]
    for note in notes or []:
        for note_line in note.splitlines():
            lines.append(f"# NOTE: {note_line}".rstrip())
    if notes:
        lines.append("")
    lines += ["", "def build_workflow() -> Workflow:", "    wf = Workflow()", ""]
    lines += body
    lines += [
        "    return wf",
        "",
        "",
        'if __name__ == "__main__":',
        '    build_workflow().run(output_dir="outputs")',
        "",
    ]
    return "\n".join(lines), warnings


def convert(
    data: Dict[str, Any],
    name: str,
    source_filename: str = "workflow.json",
    catalog: Optional[NodeCatalog] = None,
) -> ConversionResult:
    """Converts workflow JSON (either format) to a Python script."""
    catalog = catalog or NodeCatalog()
    fmt, payload = detect_format(data)
    if fmt == "ui":
        prompt, titles, notes, hints, warnings = ui_to_api(payload, catalog)
    else:
        prompt = json.loads(json.dumps(payload))
        titles = {nid: (n.get("_meta") or {}).get("title") for nid, n in prompt.items() if (n.get("_meta") or {}).get("title")}
        notes, hints, warnings = [], [], []
    if not prompt:
        raise ValueError("The workflow contains no executable nodes.")
    script, gen_warnings = generate_script(prompt, name, source_filename, catalog, titles, notes)
    # de-duplicate model hints by name
    seen, unique_hints = set(), []
    for h in hints:
        if h["name"] not in seen:
            seen.add(h["name"])
            unique_hints.append({"name": h["name"], "url": h.get("url", ""), "directory": h.get("directory", "")})
    return ConversionResult(
        script=script,
        prompt=prompt,
        format=fmt,
        node_count=len(prompt),
        titles=titles,
        notes=notes,
        model_hints=unique_hints,
        warnings=warnings + gen_warnings,
    )


# --------------------------------------------------------------------------- CLI
def main():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    parser = argparse.ArgumentParser(description="Convert ComfyUI JSON workflows to cb2c_py Python scripts.")
    parser.add_argument("-i", "--input", default=os.path.join(project_root, "json-workflows"))
    parser.add_argument("-o", "--output", default=os.path.join(project_root, "user", "workflows"))
    parser.add_argument("--object-info", help="Path to a cached ComfyUI /object_info JSON file.")
    args = parser.parse_args()

    object_info = None
    if args.object_info and os.path.exists(args.object_info):
        with open(args.object_info, "r", encoding="utf-8") as f:
            object_info = json.load(f)
    catalog = NodeCatalog(object_info)

    if not os.path.isdir(args.input):
        os.makedirs(args.input)
        print(f"Created {args.input}. Add ComfyUI JSON workflows there and run again.")
        return
    os.makedirs(args.output, exist_ok=True)
    for filename in sorted(os.listdir(args.input)):
        if not filename.endswith(".json"):
            continue
        base = sanitize_name(filename[:-5]).lower()
        try:
            with open(os.path.join(args.input, filename), "r", encoding="utf-8") as f:
                data = json.load(f)
            result = convert(data, base, filename, catalog)
        except (OSError, ValueError) as e:
            print(f"Skipped {filename}: {e}")
            continue
        out = os.path.join(args.output, base + ".py")
        with open(out, "w", encoding="utf-8") as f:
            f.write(result.script)
        print(f"{filename} -> {out}")
        for w in result.warnings:
            print(f"  warning: {w}")


if __name__ == "__main__":
    main()

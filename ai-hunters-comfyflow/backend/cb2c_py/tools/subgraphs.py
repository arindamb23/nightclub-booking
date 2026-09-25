"""Expands ComfyUI group nodes and subgraphs into ordinary nodes before conversion.

ComfyUI's browser UI does this itself when it queues a prompt, so /prompt never accepts them:

* **Legacy group nodes** – node type ``workflow>NAME`` (newer exports: ``workflow/NAME``), defined in
  ``extra.groupNodes[NAME]`` with inner ``nodes``, internal ``links`` as
  ``[from_index, from_slot, to_index, to_slot, ?, type]`` and ``external`` outputs ``[index, slot, type]``.
* **Subgraphs** (ComfyUI frontend 1.24+) – node type is a UUID defined in ``definitions.subgraphs``; links from
  node ``-10`` are the subgraph inputs, links into node ``-20`` its outputs. Subgraphs may be nested.

Inner nodes get the ids ComfyUI uses too: ``"<instance id>:<inner id>"``.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

SUBGRAPH_INPUT = -10
SUBGRAPH_OUTPUT = -20
GROUP_PREFIXES = ("workflow>", "workflow/")
CONTROL_VALUES = {"fixed", "increment", "decrement", "randomize"}
SEED_NAMES = {"seed", "noise_seed"}
MAX_DEPTH = 8


def _norm_link(link: Any) -> Optional[Dict[str, Any]]:
    if isinstance(link, dict) and "id" in link:
        return {
            "id": int(link["id"]), "origin_id": link.get("origin_id"), "origin_slot": int(link.get("origin_slot") or 0),
            "target_id": link.get("target_id"), "target_slot": int(link.get("target_slot") or 0), "type": link.get("type"),
        }
    if isinstance(link, (list, tuple)) and len(link) >= 5:
        return {
            "id": int(link[0]), "origin_id": link[1], "origin_slot": int(link[2] or 0),
            "target_id": link[3], "target_slot": int(link[4] or 0), "type": link[5] if len(link) > 5 else None,
        }
    return None


def group_name(node_type: Any) -> Optional[str]:
    if isinstance(node_type, str):
        for p in GROUP_PREFIXES:
            if node_type.startswith(p):
                return node_type[len(p):]
    return None


class _Expander:
    def __init__(self, ui: Dict[str, Any], catalog) -> None:
        self.ui = ui
        self.catalog = catalog
        self.warnings: List[str] = []
        self.nodes: Dict[str, Dict[str, Any]] = {str(n["id"]): copy.deepcopy(n) for n in ui.get("nodes") or [] if "id" in n}
        self.links: Dict[int, Dict[str, Any]] = {}
        for raw in ui.get("links") or []:
            link = _norm_link(raw)
            if link:
                link["origin_id"], link["target_id"] = str(link["origin_id"]), str(link["target_id"])
                self.links[link["id"]] = link
        self.next_link = max(self.links, default=0) + 1
        self.groups: Dict[str, Any] = ((ui.get("extra") or {}).get("groupNodes") or {})
        self.subgraphs: Dict[str, Any] = {
            sg["id"]: sg for sg in ((ui.get("definitions") or {}).get("subgraphs") or []) if isinstance(sg, dict) and sg.get("id")
        }

    # ------------------------------------------------------------------ helpers
    def _new_link(self, origin_id: str, origin_slot: int, target_id: str, target_slot: int, ltype: Any) -> int:
        lid = self.next_link
        self.next_link += 1
        self.links[lid] = {"id": lid, "origin_id": str(origin_id), "origin_slot": origin_slot,
                           "target_id": str(target_id), "target_slot": target_slot, "type": ltype}
        return lid

    def _links_from(self, node_id: str, slot: int) -> List[Dict[str, Any]]:
        return [l for l in self.links.values() if l["origin_id"] == node_id and l["origin_slot"] == slot]

    def _widget_names(self, node: Dict[str, Any]) -> Optional[List[Tuple[str, bool]]]:
        """[(widget name, has control_after_generate)] from the node catalog; None when the type is unknown."""
        entries = self.catalog.widget_inputs(node.get("type")) if self.catalog is not None else None
        if entries is None:
            return None
        out = []
        for e in entries:
            control = bool((e.get("opts") or {}).get("control_after_generate")) or (e.get("type") == "INT" and e["name"] in SEED_NAMES)
            out.append((e["name"], control))
        return out

    def _primitive(self, node_id: str, value: Any) -> str:
        """A synthetic PrimitiveNode that feeds a constant (the converter resolves it to a plain value)."""
        self.nodes[node_id] = {"id": node_id, "type": "PrimitiveNode", "widgets_values": [value], "inputs": [], "outputs": []}
        return node_id

    # ------------------------------------------------------------------ run
    def run(self) -> Dict[str, Any]:
        for _ in range(MAX_DEPTH):
            todo = [nid for nid, n in self.nodes.items() if group_name(n.get("type")) is not None or n.get("type") in self.subgraphs]
            if not todo:
                break
            for nid in todo:
                node = self.nodes.pop(nid)
                gname = group_name(node.get("type"))
                if gname is not None:
                    self._expand_group(nid, node, gname)
                else:
                    self._expand_subgraph(nid, node, self.subgraphs[node["type"]])
        out = {k: v for k, v in self.ui.items() if k not in ("nodes", "links")}
        out["nodes"] = list(self.nodes.values())
        out["links"] = [[l["id"], l["origin_id"], l["origin_slot"], l["target_id"], l["target_slot"], l["type"]]
                        for l in self.links.values()]
        return out

    # ------------------------------------------------------------------ legacy group nodes
    def _expand_group(self, gid: str, inst: Dict[str, Any], name: str) -> None:
        definition = self.groups.get(name)
        if not isinstance(definition, dict) or not definition.get("nodes"):
            self.warnings.append(f"Group node '{name}' (ID {gid}) has no definition in the workflow; it was left out.")
            self._drop_links_of(gid)
            return
        inner = sorted(copy.deepcopy(definition["nodes"]), key=lambda n: n.get("index", 0))
        for pos, n in enumerate(inner):
            n.setdefault("index", pos)
        by_index = {n["index"]: n for n in inner}
        ids = {n["index"]: f"{gid}:{n['index']}" for n in inner}
        internal_to, internal_from = set(), set()
        for l in definition.get("links") or []:
            if isinstance(l, (list, tuple)) and len(l) >= 4 and l[0] in by_index and l[2] in by_index:
                internal_from.add((l[0], int(l[1])))
                internal_to.add((l[2], int(l[3])))
        external = {(e[0], int(e[1])) for e in definition.get("external") or [] if isinstance(e, (list, tuple)) and len(e) >= 2}

        # inner nodes (fresh copies; inputs re-linked below)
        for n in inner:
            nid = ids[n["index"]]
            new = {k: v for k, v in n.items() if k not in ("index",)}
            new["id"] = nid
            if inst.get("mode") in (2, 4):
                new["mode"] = inst["mode"]
            new["inputs"] = [{**i, "link": None} for i in (n.get("inputs") or [])]
            self.nodes[nid] = new
        for l in definition.get("links") or []:
            if isinstance(l, (list, tuple)) and len(l) >= 4 and l[0] in by_index and l[2] in by_index:
                target = self.nodes[ids[l[2]]]
                slot = int(l[3])
                if slot < len(target["inputs"]):
                    target["inputs"][slot]["link"] = self._new_link(ids[l[0]], int(l[1]), ids[l[2]], slot, l[5] if len(l) > 5 else None)

        # widgets of the group = inner widgets that are not fed internally (in node order)
        widget_slots: List[Tuple[int, str, bool]] = []
        known = True
        for n in inner:
            names = self._widget_names(n)
            if names is None:
                known = False
                continue
            socket_by_name = {i.get("name"): s for s, i in enumerate(n.get("inputs") or []) if i.get("widget")}
            for wname, control in names:
                slot = socket_by_name.get(wname)
                if slot is not None and (n["index"], slot) in internal_to:
                    continue
                widget_slots.append((n["index"], wname, control))
        values = inst.get("widgets_values")
        if isinstance(values, list) and values and known:
            assigned: Dict[int, Dict[str, Any]] = {}
            i = 0
            for index, wname, control in widget_slots:
                if i >= len(values):
                    break
                assigned.setdefault(index, {})[wname] = values[i]
                i += 1
                if control and i < len(values) and isinstance(values[i], str) and values[i] in CONTROL_VALUES:
                    i += 1
            if i == len(values):
                for index, vals in assigned.items():
                    self.nodes[ids[index]]["widgets_values"] = vals  # dict: mapped by name in ui_to_api
            else:
                self.warnings.append(f"Group node '{name}' (ID {gid}): its widget values did not line up with the inner "
                                     "nodes; the values saved in the group definition were used.")
        elif isinstance(values, list) and values and not known:
            self.warnings.append(f"Group node '{name}' (ID {gid}) contains nodes that are not installed; the values saved "
                                 "in the group definition were used. Install the custom nodes and re-import for exact values.")

        # instance inputs -> inner inputs that are not fed internally
        ext_sockets = [(n["index"], s, i.get("name")) for n in inner for s, i in enumerate(n.get("inputs") or [])
                       if not i.get("widget") and (n["index"], s) not in internal_to]
        ext_widgets = [(n["index"], s, i.get("name")) for n in inner for s, i in enumerate(n.get("inputs") or [])
                       if i.get("widget") and (n["index"], s) not in internal_to]
        socket_iter = iter(ext_sockets)
        for inp in inst.get("inputs") or []:
            target = None
            if inp.get("widget"):
                wname = (inp.get("widget") or {}).get("name") or inp.get("name")
                target = next((t for t in ext_widgets if t[2] == wname or str(wname).endswith(f" {t[2]}")), None)
                if target is None:  # widget converted on the instance: add a socket on the inner node
                    for n in inner:
                        base = next((w for w, _ in (self._widget_names(n) or []) if w == wname or str(wname).endswith(f" {w}")), None)
                        if base:
                            self.nodes[ids[n["index"]]]["inputs"].append({"name": base, "type": inp.get("type"), "link": None, "widget": {"name": base}})
                            target = (n["index"], len(self.nodes[ids[n["index"]]]["inputs"]) - 1, base)
                            break
            else:
                target = next(socket_iter, None)
            link_id = inp.get("link")
            if target is None or link_id is None or int(link_id) not in self.links:
                continue
            index, slot, _ = target
            link = self.links[int(link_id)]
            link["target_id"], link["target_slot"] = ids[index], slot
            self.nodes[ids[index]]["inputs"][slot]["link"] = int(link_id)

        # instance outputs -> inner outputs that leave the group
        ext_outputs = [(n["index"], o) for n in inner for o in range(len(n.get("outputs") or []))
                       if (n["index"], o) not in internal_from or (n["index"], o) in external]
        for j, (index, o) in enumerate(ext_outputs):
            for link in self._links_from(gid, j):
                link["origin_id"], link["origin_slot"] = ids[index], o

    # ------------------------------------------------------------------ subgraphs
    def _expand_subgraph(self, iid: str, inst: Dict[str, Any], sg: Dict[str, Any]) -> None:
        inner_nodes = [n for n in sg.get("nodes") or [] if "id" in n]
        ids = {str(n["id"]): f"{iid}:{n['id']}" for n in inner_nodes}
        for n in inner_nodes:
            new = copy.deepcopy(n)
            new["id"] = ids[str(n["id"])]
            if inst.get("mode") in (2, 4):
                new["mode"] = inst["mode"]
            new["inputs"] = [{**i, "link": None} for i in (n.get("inputs") or [])]
            self.nodes[new["id"]] = new
        inst_inputs = inst.get("inputs") or []
        # promoted widget values of the instance, in the order of its widget inputs
        widget_values = inst.get("widgets_values") if isinstance(inst.get("widgets_values"), list) else []
        promoted = {}
        wi = 0
        for k, inp in enumerate(inst_inputs):
            if inp.get("widget") and wi < len(widget_values):
                promoted[k] = widget_values[wi]
                wi += 1

        def outer_origin(slot: int) -> Optional[Tuple[str, int, Any]]:
            if slot < len(inst_inputs) and inst_inputs[slot].get("link") is not None:
                link = self.links.get(int(inst_inputs[slot]["link"]))
                if link:
                    return link["origin_id"], link["origin_slot"], link["type"]
            if slot in promoted:
                return self._primitive(f"{iid}:in{slot}", promoted[slot]), 0, None
            return None

        outputs: Dict[int, Tuple[str, int]] = {}
        for raw in sg.get("links") or []:
            l = _norm_link(raw)
            if not l:
                continue
            src, dst = l["origin_id"], l["target_id"]
            if dst == SUBGRAPH_OUTPUT or str(dst) == str(SUBGRAPH_OUTPUT):
                if src == SUBGRAPH_INPUT or str(src) == str(SUBGRAPH_INPUT):
                    o = outer_origin(l["origin_slot"])
                    if o:
                        outputs[l["target_slot"]] = (o[0], o[1])
                elif str(src) in ids:
                    outputs[l["target_slot"]] = (ids[str(src)], l["origin_slot"])
                continue
            if str(dst) not in ids:
                continue
            target = self.nodes[ids[str(dst)]]
            if l["target_slot"] >= len(target["inputs"]):
                continue
            if src == SUBGRAPH_INPUT or str(src) == str(SUBGRAPH_INPUT):
                o = outer_origin(l["origin_slot"])
                if o is None:
                    continue  # unconnected subgraph input: the inner widget value stays
                target["inputs"][l["target_slot"]]["link"] = self._new_link(o[0], o[1], target["id"], l["target_slot"], l["type"] or o[2])
            elif str(src) in ids:
                target["inputs"][l["target_slot"]]["link"] = self._new_link(ids[str(src)], l["origin_slot"], target["id"], l["target_slot"], l["type"])
        for j in range(len(inst.get("outputs") or []) or len(sg.get("outputs") or [])):
            for link in self._links_from(iid, j):
                if j in outputs:
                    link["origin_id"], link["origin_slot"] = outputs[j]
                else:
                    del self.links[link["id"]]
        # the instance's own input links now end inside the subgraph
        for inp in inst_inputs:
            if inp.get("link") is not None:
                self.links.pop(int(inp["link"]), None)

    def _drop_links_of(self, node_id: str) -> None:
        for lid in [l["id"] for l in self.links.values() if node_id in (l["origin_id"], l["target_id"])]:
            del self.links[lid]


def expand_ui(ui: Dict[str, Any], catalog=None) -> Tuple[Dict[str, Any], List[str]]:
    """Returns ``(ui without group nodes/subgraphs, warnings)``. Unchanged when there is nothing to expand."""
    has_groups = any(group_name(n.get("type")) is not None for n in ui.get("nodes") or [])
    has_subgraphs = bool((ui.get("definitions") or {}).get("subgraphs"))
    if not has_groups and not has_subgraphs:
        return ui, []
    exp = _Expander(ui, catalog)
    return exp.run(), exp.warnings

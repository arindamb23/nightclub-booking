# AI Hunters ComfyFlow - cb2c_py/lib/workflow.py
"""Build a ComfyUI graph in Python and serialize it to the API ("prompt") format."""

import json
from typing import Callable, Optional, Dict, Any, List, TypeVar, Union

from cb2c_py.nodes.base_node import Node, Slot

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]
NodeType = TypeVar("NodeType", bound=Node)


class Workflow:
    """A ComfyUI workflow graph.

    Node IDs are strings (ComfyUI's API uses string keys). Pass ``node_id`` to
    keep the IDs of an imported workflow, otherwise IDs are assigned 1, 2, 3...
    """

    def __init__(self, runner=None):
        self.nodes: Dict[str, Node] = {}
        self.node_to_id: Dict[Node, str] = {}
        self._next_id = 1
        self._runner = runner

    @property
    def runner(self):
        if self._runner is None:
            from cb2c_py.lib.workflow_runner import WorkflowRunner

            self._runner = WorkflowRunner()
        return self._runner

    @runner.setter
    def runner(self, value):
        self._runner = value

    def get_nodes(self) -> List[Node]:
        return list(self.nodes.values())

    def get_node(self, node_id: Union[str, int]) -> Node:
        return self.nodes[str(node_id)]

    def add_node(self, node_instance: NodeType, node_id: Optional[Union[str, int]] = None) -> NodeType:
        """Adds a node and returns the same (typed) instance."""
        if node_instance in self.node_to_id:
            return node_instance
        if node_id is None:
            while str(self._next_id) in self.nodes:
                self._next_id += 1
            node_id = self._next_id
            self._next_id += 1
        node_id = str(node_id)
        if node_id in self.nodes:
            raise ValueError(f"Duplicate node id '{node_id}'")
        self.nodes[node_id] = node_instance
        self.node_to_id[node_instance] = node_id
        node_instance.id = node_id
        return node_instance

    def _serialize_value(self, owner_id: str, name: str, value: Any) -> Any:
        if isinstance(value, Slot):
            source = value._node
            if source not in self.node_to_id:
                raise ValueError(
                    f"Input '{name}' of node {owner_id} is linked to a "
                    f"{getattr(source, '_original_name', source)} node that was never added "
                    "with wf.add_node()"
                )
            return [self.node_to_id[source], source.output_index(value)]
        return value

    def to_prompt(self) -> Dict[str, Any]:
        """Returns the ComfyUI API-format dict ``{id: {inputs, class_type, _meta}}``.

        Inputs whose value is None (unset optional inputs) are omitted.
        """
        prompt: Dict[str, Any] = {}
        for node_id, node in self.nodes.items():
            values = node.serializable_inputs() if hasattr(node, "serializable_inputs") else dict(node.input_values)
            inputs = {
                name: self._serialize_value(node_id, name, value)
                for name, value in values.items()
                if value is not None
            }
            entry = {"inputs": inputs, "class_type": node._original_name}
            title = node.__dict__.get("_properties", {}).get("title") if hasattr(node, "__dict__") else None
            if title:
                entry["_meta"] = {"title": title}
                entry["inputs"].pop("title", None)
            prompt[node_id] = entry
        return prompt

    def build_workflow_json(self, indent: int = 4) -> str:
        """Backwards compatible JSON string ``{"prompt": {...}}``."""
        return json.dumps({"prompt": self.to_prompt()}, indent=indent)

    def run(self, progress_callback: ProgressCallback = None, output_dir: str = "outputs"):
        """Executes the workflow with the WorkflowRunner and returns the saved files."""
        return self.runner.run_workflow(self, progress_callback, output_dir=output_dir)

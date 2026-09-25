# AI Hunters ComfyFlow - cb2c_py/lib/workflow_interface.py
from typing import Protocol, Dict, Any, List
from cb2c_py.nodes.base_node import Node


class WorkflowInterface(Protocol):
    """Interface for the Workflow class, used to break circular imports."""

    nodes: Dict[str, Node]

    def to_prompt(self) -> Dict[str, Any]: ...
    def build_workflow_json(self, indent: int = 4) -> str: ...
    def get_nodes(self) -> List[Node]: ...

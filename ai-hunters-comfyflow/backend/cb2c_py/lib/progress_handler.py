# AI Hunters ComfyFlow - cb2c_py/lib/progress_handler.py
from typing import Dict, Any, Optional
from tqdm import tqdm


class ComfyUIProgressHandler:
    """
    A callback handler for ComfyUI workflow progress, using tqdm for visualization.
    Each node with progress will have its own progress bar.
    """

    def __init__(self, name: Optional[str] = None, workflow: Optional[Any] = None):
        self.pbar = None
        self.workflow = workflow
        if name is not None:
            self.name = name
        else:
            self.name = "Workflow Progress"
        self.current_node_id = None

    def __call__(self, message: Dict[str, Any]):
        """
        Processes progress messages from ComfyUI.
        """
        if message["type"] == "progress":
            data = message["data"]
            if self.pbar is None:
                desc = (
                    f"{self.name} (Node: {self.current_node_id})"
                    if self.current_node_id
                    else self.name
                )
                self.pbar = tqdm(total=data["max"], desc=desc, unit="step")

            current_value = data["value"]
            if current_value > self.pbar.n:
                self.pbar.update(current_value - self.pbar.n)
        elif message["type"] == "executing":
            data = message["data"]
            if self.pbar:
                # A new node (or the end of the run) closes the previous bar.
                if self.pbar.n < self.pbar.total:
                    self.pbar.update(self.pbar.total - self.pbar.n)
                self.pbar.close()
                self.pbar = None
            self.current_node_id = data["node"]
            if data["node"] is not None and self.workflow is not None:
                node = self.workflow.nodes.get(str(data["node"]))
                if node is not None:
                    self.current_node_id = f"{data['node']} {node._original_name}"
        elif message["type"] == "status":
            data = message["data"]
            exec_info = data.get("exec_info")
            if exec_info and exec_info.get("queue_remaining") == 0 and self.pbar:
                self.pbar.close()
                self.pbar = None
            # print(f"Status: {data.get('exec_info')}") # Uncomment for more detailed status
        # else:
        # print(f"Received message: {message['type']}") # Uncomment to see all message types

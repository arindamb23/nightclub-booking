# AI Hunters ComfyFlow - cb2c_py/nodes/base_node.py
"""Base classes shared by every generated ComfyUI node wrapper."""

from typing import Optional, TypeVar, Generic, List, Dict, Any


# Marker classes used only for static type hints.
class Model: ...


class Conditioning: ...


class Latent: ...


class Image: ...


class Vae: ...


class Clip: ...


T = TypeVar("T")

# Properties that steer the runner and must never be sent to ComfyUI.
META_PROPERTIES = frozenset({"upload"})


class Slot(Generic[T]):
    """A single input or output socket of a node.

    ``_index`` is optional: when set it is the output index used for the link,
    otherwise the index is derived from the owning node's output order.
    """

    def __init__(self, node: "Node", name: str, slot_type: Any, index: Optional[int] = None):
        self._node = node
        self._name = name
        self._type = slot_type
        self._index = index

    def __repr__(self):
        owner = getattr(self._node, "_original_name", type(self._node).__name__)
        return f"Slot(node={owner}, name='{self._name}', type='{self._type}')"

    __str__ = __repr__


class InputSlots:
    """Base class for a node's input slots."""


class OutputSlots:
    """Base class for a node's output slots."""


I = TypeVar("I", bound=InputSlots)
O = TypeVar("O", bound=OutputSlots)


class Node(Generic[I, O]):
    """Base class for all ComfyUI nodes.

    Constructor values live in ``input_values``. Assigning an attribute whose
    name matches a declared input (``node.image2 = other.outputs.image``)
    updates that input; any other attribute is stored in ``_properties`` and is
    serialized as an extra input, except runner flags such as ``upload``.
    """

    _original_name: str = "BaseNode"
    inputs: I
    outputs: O
    _properties: Dict[str, Any]

    _KNOWN_ATTRS = ("original_name", "input_values", "id", "workflow", "inputs", "outputs")

    def __init__(self, **kwargs):
        self.original_name = self._original_name
        self.input_values = kwargs
        self.id: Optional[str] = None
        super().__setattr__("_properties", {})

    def __setattr__(self, name: str, value: Any):
        if name.startswith("_") or name in self._KNOWN_ATTRS:
            super().__setattr__(name, value)
            return
        declared = self.__dict__.get("inputs")
        if name in self.__dict__.get("input_values", {}) or (
            declared is not None and name in vars(declared)
        ):
            self.input_values[name] = value
        else:
            self._properties[name] = value

    def __getattr__(self, name: str) -> Any:
        props = self.__dict__.get("_properties")
        if props is not None and name in props:
            return props[name]
        values = self.__dict__.get("input_values")
        if values is not None and name in values:
            return values[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def set_input(self, name: str, value: Any) -> "Node":
        """Set an input by its original ComfyUI name (works for any name)."""
        self.input_values[name] = value
        return self

    def get_outputs(self) -> List[str]:
        """Returns the node's output slot names in ComfyUI order."""
        return [slot._name for slot in vars(self.outputs).values()]

    def output(self, index: int) -> Slot:
        """Returns the output slot at ``index`` (ComfyUI order)."""
        slots = list(vars(self.outputs).values())
        if index >= len(slots):
            raise IndexError(f"{self._original_name} has no output #{index}")
        return slots[index]

    def output_index(self, slot: Slot) -> int:
        """Returns the ComfyUI output index of ``slot``."""
        if slot._index is not None:
            return slot._index
        slots = list(vars(self.outputs).values())
        for i, s in enumerate(slots):
            if s is slot:
                return i
        names = [s._name for s in slots]
        return names.index(slot._name)

    def serializable_inputs(self) -> Dict[str, Any]:
        """Constructor inputs merged with extra properties (runner flags excluded)."""
        extra = {k: v for k, v in self._properties.items() if k not in META_PROPERTIES}
        return {**self.input_values, **extra}

    def to_dict(self):
        """Serializes the node (links left as Slot objects)."""
        return {"inputs": self.serializable_inputs(), "class_type": self.original_name}


class GenericOutputs(OutputSlots):
    """Outputs of a node that has no generated wrapper; slots are created on demand."""

    def __init__(self, node: "Node"):
        pass


class GenericNode(Node[InputSlots, GenericOutputs]):
    """Wrapper for any ComfyUI node type, including ones without a generated class.

    Example: ``GenericNode("MyCustomNode", {"strength": 0.5, "image": img.outputs.image})``
    and link its outputs with ``node.output(0)``.
    """

    def __init__(self, class_type: str, inputs: Optional[Dict[str, Any]] = None, **kwargs):
        super().__setattr__("_original_name", class_type)
        super().__init__(**{**(inputs or {}), **kwargs})
        self.inputs = InputSlots()
        self.outputs = GenericOutputs(self)
        super().__setattr__("_generic_slots", {})

    def __setattr__(self, name: str, value: Any):
        if name.startswith("_") or name in self._KNOWN_ATTRS:
            super().__setattr__(name, value)
        else:
            self.input_values[name] = value

    def output(self, index: int) -> Slot:
        slots = self.__dict__["_generic_slots"]
        if index not in slots:
            slots[index] = Slot(self, f"output_{index}", "*", index=index)
        return slots[index]

    def output_index(self, slot: Slot) -> int:
        return slot._index if slot._index is not None else 0

    def get_outputs(self) -> List[str]:
        return [s._name for _, s in sorted(self.__dict__["_generic_slots"].items())]

"""JSON encoding helpers shared by the domain model.

The JSON form of the domain objects is a public contract: problem files, run
files, checkpoints, the blackboard and the UI all persist it. Each class
therefore writes its own ``to_dict``/``from_dict`` instead of relying on field
reflection, so that renaming an internal attribute never silently changes a
stored document.

``jsonable`` only handles the *encoding* direction, where a generic walk is
safe; decoding stays explicit in each ``from_dict``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

JSON = dict[str, Any]

#: Suffix of the temporary file a document is written through, beside its target.
WRITING_SUFFIX = ".writing"


def jsonable(value: Any) -> Any:
    """Recursively turn ``value`` into JSON-compatible primitives.

    Understands domain objects (anything exposing ``to_dict``), numpy scalars
    and arrays, enums, paths, mappings and sequences. Anything else raises
    ``TypeError`` so that a forgotten type fails loudly instead of being
    stringified into a file that cannot be read back.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return float(value)
    if isinstance(value, Enum):
        return jsonable(value.value)
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return jsonable(to_dict())
    to_list = getattr(value, "tolist", None)  # numpy arrays
    if callable(to_list):
        return jsonable(to_list())
    item = getattr(value, "item", None)  # numpy scalars
    if callable(item):
        return jsonable(item())
    raise TypeError(f"cannot serialise {type(value).__name__} to JSON")


def dumps(value: Any, *, indent: int | None = 2) -> str:
    """Serialise ``value`` with ``NaN``/``Infinity`` rejected."""
    return json.dumps(jsonable(value), indent=indent, ensure_ascii=False, allow_nan=False)


def dump(value: Any, path: str | Path, *, indent: int | None = 2) -> Path:
    """Write ``value`` as JSON, creating parent directories as needed.

    The text lands in a temporary file beside the target and is renamed onto it, so a reader
    polling the file sees the previous document or the new one and never half of either: a
    run is rewritten after every turn while the interface reads it back.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + WRITING_SUFFIX)
    temporary.write_text(dumps(value, indent=indent) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def load(path: str | Path) -> Any:
    """Read a JSON document from ``path``."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(data: Mapping[str, Any], key: str, where: str) -> Any:
    """Return ``data[key]``, or raise a located error naming the missing field."""
    try:
        return data[key]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{where}: missing required field {key!r}") from exc


def optional(data: Mapping[str, Any], key: str, default: Any = None) -> Any:
    """Return ``data[key]`` when present and not null, else ``default``."""
    value = data.get(key, default)
    return default if value is None else value


def discriminated(kind: str, builders: Mapping[str, Any], payload: Mapping[str, Any], where: str) -> Any:
    """Decode ``payload`` with the ``builders`` entry named by its ``type`` field."""
    payload_type = require(payload, "type", where)
    builder = builders.get(payload_type)
    if builder is None:
        known = ", ".join(sorted(builders))
        raise ValueError(f"{where}: unknown type {payload_type!r} (known: {known})")
    return builder(payload)


def as_float(value: Any, where: str) -> float:
    """Coerce a JSON number to ``float``, rejecting booleans and strings by accident."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: expected a number, got {type(value).__name__}")
    return float(value)


def as_int(value: Any, where: str) -> int:
    """Coerce a JSON integer, rejecting floats that would silently truncate."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where}: expected an integer, got {type(value).__name__}")
    return int(value)

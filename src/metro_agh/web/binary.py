"""Header + .bin pairs (docs/data_contracts.md, section 10.6)."""

from pathlib import Path

import numpy as np

from ..schemas.web import BufferView

_DTYPES = {
    np.dtype(np.uint8): "uint8",
    np.dtype(np.int16): "int16",
    np.dtype(np.uint16): "uint16",
    np.dtype(np.int32): "int32",
    np.dtype(np.uint32): "uint32",
    np.dtype(np.float32): "float32",
}


def pack(arrays: dict[str, np.ndarray]) -> tuple[bytes, dict[str, BufferView]]:
    """Concatenate little-endian buffers, each starting at a multiple of 4 bytes."""
    data = bytearray()
    views = {}
    for name, arr in arrays.items():
        arr = np.ascontiguousarray(arr)
        dtype = _DTYPES.get(arr.dtype)
        if dtype is None:
            raise TypeError(f"{name}: dtype {arr.dtype} is not allowed in web binaries")
        data += b"\0" * (-len(data) % 4)
        views[name] = BufferView(
            dtype=dtype, offset=len(data), count=arr.size, shape=list(arr.shape)
        )
        data += arr.astype(arr.dtype.newbyteorder("<"), copy=False).tobytes()
    return bytes(data), views


def write_binary(json_path: Path, model, arrays: dict[str, np.ndarray], **fields) -> None:
    """Write ``<name>.bin`` and its header ``<name>.json`` (an instance of ``model``)."""
    json_path = Path(json_path)
    data, views = pack(arrays)
    bin_path = json_path.with_suffix(".bin")
    header = model(bin=bin_path.name, buffers=views, **fields)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_bytes(data)
    json_path.write_text(header.model_dump_json(), encoding="utf-8")

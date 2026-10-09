"""Load a building YAML and turn every failure into BuildErrors with a line number.

Pydantic reports where an error is (``levels.1.rooms.3.width``) and the YAML parser knows
the line of every node, so each error gets the line of the deepest node its location
reaches. Errors of the whole-building check (one message, ``a; b; c``) are split and placed
by the room, stairs, corridor or entrance they name.
"""

import re
from pathlib import Path

import pydantic
import yaml

from ..schemas import load_building
from ..schemas.building import Building
from ..schemas.web import BuildError

_SPACE_KINDS = ("rooms", "stairs", "corridors")
_NAMED = re.compile(r"(?:level (-?\d+) )?(room|stairs|corridor|entrance) '([^']+)'")
_LEVEL = re.compile(r"level (-?\d+)")


def line_index(text: str) -> dict[tuple, int]:
    """YAML path (keys and list indices) -> 1-based line."""
    out: dict[tuple, int] = {}

    def walk(node, path: tuple) -> None:
        out.setdefault(path, node.start_mark.line + 1)
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                walk(value, (*path, key.value))
                out[(*path, key.value)] = key.start_mark.line + 1
        elif isinstance(node, yaml.SequenceNode):
            for i, value in enumerate(node.value):
                walk(value, (*path, i))

    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if root is not None:
        walk(root, ())
    return out


def _line(lines: dict[tuple, int], loc: tuple) -> int | None:
    for n in range(len(loc), -1, -1):
        if loc[:n] in lines:
            return lines[loc[:n]]
    return None


def _element(raw, loc: tuple) -> str | None:
    """Id of the space or entrance a location points into."""
    try:
        if len(loc) >= 4 and loc[0] == "levels" and loc[2] in _SPACE_KINDS:
            return str(raw["levels"][loc[1]][loc[2]][loc[3]]["id"])
        if len(loc) >= 2 and loc[0] == "entrances":
            return str(raw["entrances"][loc[1]]["id"])
    except (KeyError, IndexError, TypeError):
        return None
    return None


def _find(raw, text: str) -> tuple[tuple, str | None]:
    """YAML path and element named in a building-level message."""
    levels = raw.get("levels") or [] if isinstance(raw, dict) else []
    m = _NAMED.search(text)
    if m:
        level, kind, ident = m.groups()
        if kind == "entrance":
            for j, e in enumerate(raw.get("entrances") or []):
                if str(e.get("id")) == ident:
                    return ("entrances", j), ident
            return ("entrances",), ident
        key = {"room": "rooms", "stairs": "stairs", "corridor": "corridors"}[kind]
        for i, lvl in enumerate(levels):
            if level is not None and str(lvl.get("id")) != level:
                continue
            for j, item in enumerate(lvl.get(key) or []):
                if str(item.get("id")) == ident:
                    return ("levels", i, key, j), ident
        return (), ident
    m = _LEVEL.search(text)
    if m:
        for i, lvl in enumerate(levels):
            if str(lvl.get("id")) == m.group(1):
                return ("levels", i), None
    return (), None


def load_with_errors(path: Path, rel: str) -> tuple[Building | None, list[BuildError]]:
    path = Path(path)
    bid = path.stem
    text = path.read_text(encoding="utf-8")
    try:
        return load_building(path), []
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        msg = str(getattr(err, "problem", None) or err)
        return None, [BuildError(file=rel, line=line, message=msg, building_id=bid)]
    except pydantic.ValidationError as err:
        raw = yaml.safe_load(text)
        lines = line_index(text)
        out = []
        for e in err.errors():
            loc = tuple(e["loc"])
            msg = e["msg"].removeprefix("Value error, ")
            if loc == () and msg.startswith(f"building {bid}: "):
                for part in msg.removeprefix(f"building {bid}: ").split("; "):
                    where, element = _find(raw, part)
                    out.append(
                        BuildError(
                            file=rel, line=_line(lines, where) if where else None,
                            loc=".".join(map(str, where)) or None, message=part,
                            building_id=bid, element=element,
                        )
                    )  # fmt: skip
                continue
            out.append(
                BuildError(
                    file=rel, line=_line(lines, loc), loc=".".join(map(str, loc)) or None,
                    message=msg, building_id=bid, element=_element(raw, loc),
                )
            )  # fmt: skip
        return None, out
    except ValueError as err:  # id does not match the file name, ...
        return None, [BuildError(file=rel, line=_line(line_index(text), ("id",)), message=str(err),
                                 building_id=bid)]  # fmt: skip

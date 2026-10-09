"""Write JSON Schemas of all JSON/YAML contracts to ``schemas/``.

- ``schemas/building.schema.json`` / ``campus.schema.json`` give autocompletion and
  validation while editing YAML in VS Code (redhat.vscode-yaml).
- ``schemas/web/*.schema.json`` are turned into TypeScript types for the viewer
  (``npm run gen:types`` in web/, json-schema-to-typescript).

Run: ``uv run python -m metro_agh.schemas.export``. A test fails if the files are stale.
"""

import json
from pathlib import Path

from .building import Building
from .campus import Campus
from .instance import InstanceMeta
from .results import BestLine, RunMeta
from .web import WEB_MODELS

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "schemas"


def render_all() -> dict[str, str]:
    """Relative path -> file content."""
    # hand-written inputs: "validation" schemas (fields with defaults may be omitted);
    # web files are written in full: "serialization" schemas (every field is present)
    models = {
        "building.schema.json": (Building, "validation"),
        "campus.schema.json": (Campus, "validation"),
        "instance_meta.schema.json": (InstanceMeta, "validation"),
        "best_line.schema.json": (BestLine, "validation"),
        "run.schema.json": (RunMeta, "validation"),
        **{
            f"web/{name}.schema.json": (model, "serialization")
            for name, model in WEB_MODELS.items()
        },
    }
    return {
        path: json.dumps(model.model_json_schema(mode=mode), indent=2, ensure_ascii=False) + "\n"
        for path, (model, mode) in models.items()
    }


def main() -> None:
    for rel, content in render_all().items():
        out = SCHEMA_DIR / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

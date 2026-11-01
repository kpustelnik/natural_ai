"""Assemble the GitHub Pages site in _site/ (the workflow .github/workflows/pages.yml).

    uv run scripts/06_export_web.py --campus --aco --metro --sim   # viewer data
    cd web && npm run build -- --base=./ && cd ..                  # viewer -> web/dist
    uv run scripts/build_slides.py                                 # slides -> docs/prezentacje
    uv run scripts/build_site.py                                   # -> _site/
    python -m http.server -d _site                                 # preview on :8000

Layout of the site (all links relative, so it works under any base path):

    index.html, etap-1/, etap-2/, assets/   from site/ (hand-written pages)
    viewer/                                 web/dist (the 3D viewer with its data/)
    prezentacje/prezentacja-{1,2}.html      the slides (docs/prezentacje/)
    figures/*.png                           docs/figures/ (slides and the stage-2 page)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(out: Path, viewer: Path) -> None:
    if not (viewer / "index.html").exists():
        raise SystemExit(f"{viewer} has no index.html: run `npm run build -- --base=./` in web/")
    if not (viewer / "data" / "scene.json").exists():
        raise SystemExit(f"{viewer}/data has no scene.json: run 06_export_web.py before the build")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.copytree(viewer, out / "viewer")
    (out / "prezentacje").mkdir()
    for deck in sorted((ROOT / "docs" / "prezentacje").glob("*.html")):
        shutil.copy2(deck, out / "prezentacje" / deck.name)
    (out / "figures").mkdir()
    for fig in sorted((ROOT / "docs" / "figures").glob("*.png")):
        shutil.copy2(fig, out / "figures" / fig.name)
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"wrote {out} ({size / 2**20:.0f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "_site"), help="output folder")
    parser.add_argument("--viewer", default=str(ROOT / "web" / "dist"), help="built viewer")
    args = parser.parse_args()
    build(Path(args.out), Path(args.viewer))
    return 0


if __name__ == "__main__":
    sys.exit(main())

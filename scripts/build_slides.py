"""Build the presentations in docs/prezentacje/ into single HTML files you open in a browser.

    uv run scripts/build_slides.py            # every deck
    uv run scripts/build_slides.py prezentacja-2

A deck is a folder ``docs/prezentacje/<deck>/`` in the format of the Slides artifacts the
decks were made in (``deck.json``: title, slide order, fonts; ``slides/<id>.html``: one
``<section>`` per slide on a 1920×1080 canvas, inline styles, speaker notes in ``<aside>``).
``assets.json`` maps the artifact's uploaded images (``/_blob/<id>``) to files in
``docs/figures/``, so the figures come from the repo.

Writes ``docs/prezentacje/<deck>.html``: every slide scaled to the window, the speaker notes
under it, arrows / PageUp / PageDown jump between slides. The slide sources stay the
reference: edit them, then rebuild. Outline and demo script: docs/prezentacja.md.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECKS = ROOT / "docs" / "prezentacje"

CSS = """
:root { color-scheme: light; }
body { margin: 0; background: #e7e6e1; font-family: 'Public Sans', Arial, sans-serif; }
header { padding: 16px 24px; font-size: 15px; color: #3b4250; }
header b { color: #1c2430; }
.slide { margin: 0 auto 8px; width: min(100vw - 32px, 1600px); }
.frame { position: relative; overflow: hidden; background: #fbfbf8; aspect-ratio: 16 / 9;
         box-shadow: 0 2px 12px rgba(0,0,0,.15); }
.frame > section { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px;
                   box-sizing: border-box; overflow: hidden; transform-origin: 0 0; }
section * { margin: 0; box-sizing: border-box; }
section ul, section ol { padding-left: 1.2em; }
section table { width: 100%; border-collapse: collapse; }
section th { font-weight: 600; }
section th, section td { padding: .35em .6em; border-bottom: 1px solid rgba(0,0,0,.18);
                         vertical-align: top; }
section aside { display: none; }
.notes { font-size: 15px; color: #3b4250; padding: 10px 4px 28px; line-height: 1.5; }
.notes summary { cursor: pointer; color: #1c2430; }
.num { float: right; color: #6b7280; }
"""

JS = """
const frames = [...document.querySelectorAll('.frame')];
function fit() {
  for (const f of frames) {
    f.firstElementChild.style.transform = 'scale(' + f.clientWidth / 1920 + ')';
  }
}
addEventListener('resize', fit); fit();
addEventListener('keydown', (e) => {
  const step = {ArrowDown: 1, ArrowRight: 1, PageDown: 1, ' ': 1,
                ArrowUp: -1, ArrowLeft: -1, PageUp: -1}[e.key];
  if (!step) return;
  e.preventDefault();
  const tops = frames.map((f) => f.getBoundingClientRect().top);
  let i = tops.findIndex((t) => t > 2);
  i = i < 0 ? frames.length : i;
  const now = step > 0 ? i : Math.max(0, i - 2);
  frames[Math.min(frames.length - 1, now)].scrollIntoView({behavior: 'smooth'});
});
"""


def _style(attrs: str) -> dict[str, str]:
    m = re.search(r'style="([^"]*)"', attrs)
    out = {}
    for part in (m.group(1) if m else "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _px(v: str | None, default: int) -> int:
    return int(float(v.removesuffix("px"))) if v else default


def _shape(m: re.Match) -> str:
    """``<x-shape kind="arrow-right">``: a block arrow, the head the last 40% of its length."""
    st = _style(m.group(2))
    w, h, fill = _px(st.get("width"), 96), _px(st.get("height"), 48), st.get("background", "#000")
    if m.group(1) != "arrow-right":
        return f'<div style="width:{w}px;height:{h}px;background:{fill}"></div>'
    neck, body = h * 0.3, w * 0.6
    path = f"M0 {neck} H{body} V0 L{w} {h / 2} L{body} {h} V{h - neck} H0 Z"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<path d="{path}" fill="{fill}"/></svg>')  # fmt: skip


ICONS = {
    "CheckCircle": '<circle cx="12" cy="12" r="10"/><path d="M7.5 12.5l3 3 6-6.5"/>',
    "Clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6.5V12l3.5 2"/>',
    "Check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
}


def _icon(m: re.Match) -> str:
    st = _style(m.group(2))
    w, h = _px(st.get("width"), 32), _px(st.get("height"), 32)
    body = ICONS.get(m.group(1), '<circle cx="12" cy="12" r="10"/>')
    color = st.get("color", "currentColor")
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true" style="flex:none">{body}</svg>')  # fmt: skip


def slide_html(text: str, assets: dict[str, str]) -> tuple[str, str]:
    """(the section, ready for a browser; its speaker notes as plain text)."""
    for blob, name in assets.items():
        text = text.replace(f'src="{blob}"', f'src="../figures/{name}"')
    text = re.sub(r'<x-shape kind="([^"]+)"([^>]*)></x-shape>', _shape, text)
    text = re.sub(r'<x-icon name="([^"]+)"([^>]*)></x-icon>', _icon, text)
    notes = re.search(r"<aside>(.*?)</aside>", text, re.S)
    return text, html.unescape(notes.group(1).strip()) if notes else ""


def build(deck_dir: Path) -> Path:
    deck = json.loads((deck_dir / "deck.json").read_text(encoding="utf-8"))
    assets_file = deck_dir / "assets.json"
    assets = json.loads(assets_file.read_text(encoding="utf-8")) if assets_file.exists() else {}
    fonts = "".join(
        f'<link rel="stylesheet" href="{html.escape(f["href"])}">\n'
        for f in deck.get("faces", {}).values()
        if f.get("href")
    )
    title = html.escape(deck["title"])
    parts = []
    order = deck["order"]
    for n, sid in enumerate(order, 1):
        section, notes = slide_html(
            (deck_dir / "slides" / f"{sid}.html").read_text(encoding="utf-8"), assets
        )
        note = (f'<details class="notes"><summary>Notatki</summary>{html.escape(notes)}</details>'
                if notes else '<div class="notes"></div>')  # fmt: skip
        parts.append(f'<div class="slide" id="slide-{n}"><div class="frame">{section}</div>'
                     f'<span class="num">{n} / {len(order)}</span>{note}</div>')  # fmt: skip
    page = (
        f'<!doctype html>\n<html lang="pl">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n{fonts}<style>{CSS}</style>\n</head>\n<body>\n"
        f"<header><b>{title}</b> · {len(order)} slajdów · strzałki / PageUp / PageDown: "
        f"następny / poprzedni · źródła: docs/prezentacje/{deck_dir.name}/ · "
        f"wygenerowane przez scripts/build_slides.py</header>\n"
        + "\n".join(parts)
        + f"\n<script>{JS}</script>\n</body>\n</html>\n"
    )
    out = DECKS / f"{deck_dir.name}.html"
    out.write_text(page, encoding="utf-8", newline="\n")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("decks", nargs="*", help="deck folder names (default: all)")
    args = parser.parse_args()
    names = args.decks or sorted(p.name for p in DECKS.iterdir() if (p / "deck.json").exists())
    for name in names:
        print(f"wrote {build(DECKS / name).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

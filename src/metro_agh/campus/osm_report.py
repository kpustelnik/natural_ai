"""Human-facing outputs of the OSM stage: report.md and preview.html."""

import datetime as dt
import json
from pathlib import Path

import geopandas as gpd

from .bootstrap import BootstrapResult
from .osm_process import Issues


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return f"{v:g}" if isinstance(v, float) else str(v)


def write_report(
    path: Path,
    layers: dict[str, gpd.GeoDataFrame],
    issues: Issues,
    boot: BootstrapResult | None,
) -> None:
    b, e, s = layers["buildings"], layers["entrances"], layers["stops"]
    edges = layers["walk_edges"]
    places = b[b.building_id.notna()].sort_values("building_id")
    lines = [
        "# OSM campus report",
        "",
        f"Generated {dt.datetime.now().isoformat(timespec='seconds')}. "
        "Data © OpenStreetMap contributors, ODbL.",
        "",
        "## Summary",
        "",
        "| what | count |",
        "|---|---|",
        *[
            f"| buildings: {cat} | {n} |"
            for cat, n in b.category.value_counts().sort_index().items()
        ],
        f"| entrances (on AGH buildings) | {len(e)} ({e.building_id.notna().sum()}) |",
        f"| stops | {len(s)} |",
        f"| walk nodes / edges | {len(layers['walk_nodes'])} / {len(edges)} |",
        f"| walk network length | {edges.length_m.sum() / 1000:.1f} km |",
        f"| steps edges | {int(edges.is_steps.sum())} |",
        f"| point barriers / fences | {len(layers['barriers'])} / {len(layers['fences'])} |",
        "",
    ]
    if boot is not None:
        lines += [
            "## Building YAML bootstrap",
            "",
            f"- written: {len(boot.written)}"
            + (f" ({', '.join(boot.written)})" if boot.written else ""),
            f"- skipped (file exists): {len(boot.skipped)}"
            + (f" ({', '.join(boot.skipped)})" if boot.skipped else ""),
            f"- failed: {len(boot.failed)}",
            "",
        ]
    lines += ["## Issues to check", ""]
    if not issues.items:
        lines += ["None.", ""]
    for section, items in issues.items.items():
        lines += [f"### {section} ({len(items)})", "", *[f"- {i}" for i in sorted(items)], ""]

    lines += [
        "## AGH buildings",
        "",
        "| id | category | name | levels | height m (source) | entrances | main entrance | OSM |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in places.itertuples():
        lines.append(
            f"| {r.building_id} | {r.category} | {_fmt(r.name)} | {_fmt(r.levels)} | "
            f"{r.height_m:.1f} ({r.height_source}) | {r.n_entrances} | "
            f"{_fmt(r.main_entrance_node)} | {r.osm_ids.replace('|', ', ')} |"
        )
    lines += ["", "## Stops", "", "| id | name | modes | platforms |", "|---|---|---|---|"]
    lines += [f"| `{r.stop_id}` | {r.name} | {r.modes} | {r.n_platforms} |" for r in s.itertuples()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# --- preview.html ---------------------------------------------------------------------

_STYLE = {
    "academic": "#c8102e",
    "dorm": "#2f6fb5",
    "other": "#8a5a9c",
    "connector": "#e08a00",
    "context": "#9a9a9a",
}

_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OSM campus preview</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  html, body, #map { margin: 0; height: 100%; }
  .legend { background: white; padding: 8px 10px; font: 13px system-ui, sans-serif;
            border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.3); }
  .legend i { display: inline-block; width: 12px; height: 12px; margin-right: 6px;
              vertical-align: -1px; border-radius: 2px; }
  .leaflet-popup-content table { border-collapse: collapse; font-size: 12px; }
  .leaflet-popup-content td { padding: 1px 6px 1px 0; vertical-align: top; }
  .leaflet-popup-content td:first-child { color: #666; }
</style>
</head>
<body>
<div id="map"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById("data").textContent);
const style = __STYLE__;
const map = L.map("map", { preferCanvas: true });
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 20, maxNativeZoom: 19,
  attribution: "© OpenStreetMap contributors",
}).addTo(map);

function popup(f, layer) {
  const rows = Object.entries(f.properties)
    .filter(([, v]) => v !== null && v !== "" && v !== false)
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  layer.bindPopup(`<table>${rows}</table>`);
}

const layers = {
  "Boundary": L.geoJSON(data.boundary, {
    style: { color: "#333", weight: 2, dashArray: "6 4", fill: false }, interactive: false }),
  "Walk network": L.geoJSON(data.walk_edges, {
    style: f => f.properties.is_steps
      ? { color: "#d6336c", weight: 4 } : { color: "#2b8a3e", weight: 2, opacity: 0.7 },
    onEachFeature: popup }),
  "Buildings": L.geoJSON(data.buildings, {
    style: f => ({ color: style[f.properties.category], weight: 1,
                   fillOpacity: f.properties.category === "context" ? 0.25 : 0.55 }),
    onEachFeature: (f, l) => { popup(f, l); if (f.properties.building_id)
      l.bindTooltip(f.properties.building_id, { permanent: false }); } }),
  "Fences": L.geoJSON(data.fences, { style: { color: "#7a4b00", weight: 1.5 }, onEachFeature: popup }),
  "Barriers": L.geoJSON(data.barriers, {
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3, color: "#7a4b00", fillOpacity: 1 }),
    onEachFeature: popup }),
  "Entrances": L.geoJSON(data.entrances, {
    pointToLayer: (f, ll) => L.circleMarker(ll, f.properties.is_main
      ? { radius: 6, color: "#000", weight: 2, fillColor: "#ffd43b", fillOpacity: 1 }
      : { radius: 3, color: "#000", weight: 1, fillColor: "#fff", fillOpacity: 1 }),
    onEachFeature: popup }),
  "Stops": L.geoJSON(data.stops, {
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 8, color: "#fff", weight: 2,
      fillColor: "#1c7ed6", fillOpacity: 1 }),
    onEachFeature: (f, l) => { popup(f, l); l.bindTooltip(f.properties.name); } }),
};
Object.values(layers).forEach(l => l.addTo(map));
L.control.layers(null, layers, { collapsed: false }).addTo(map);
map.fitBounds(layers["Boundary"].getBounds());

const legend = L.control({ position: "bottomleft" });
legend.onAdd = () => {
  const div = L.DomUtil.create("div", "legend");
  div.innerHTML = Object.entries(style).map(([k, c]) => `<div><i style="background:${c}"></i>${k}</div>`).join("")
    + '<div><i style="background:#ffd43b;border:1px solid #000"></i>main entrance</div>'
    + '<div><i style="background:#d6336c"></i>steps</div>';
  return div;
};
legend.addTo(map);
</script>
</body>
</html>
"""


def write_preview(path: Path, layers: dict[str, gpd.GeoDataFrame]) -> None:
    payload = {}
    for name in ("boundary", "buildings", "entrances", "stops", "barriers", "fences", "walk_edges"):
        gdf = layers[name].to_crs("EPSG:4326")
        payload[name] = json.loads(gdf.to_json(drop_id=True, to_wgs84=False, na="null"))
        for f in payload[name]["features"]:
            f["geometry"] = _round(f["geometry"])
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = _HTML.replace("__DATA__", data).replace("__STYLE__", json.dumps(_STYLE))
    path.write_text(html, encoding="utf-8", newline="\n")


def _round(geom: dict | None, nd: int = 6) -> dict | None:
    if geom is None:
        return None

    def r(c):
        return [round(c[0], nd), round(c[1], nd)] if isinstance(c[0], float) else [r(x) for x in c]

    return {**geom, "coordinates": r(geom["coordinates"])}

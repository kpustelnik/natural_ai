"""Public transport around the campus from the Kraków GTFS feeds (ZTP Kraków, open data).

Two questions:

- **Where do commuters get off?** Every stop in ``campus.bbox`` widened by
  ``transit.margin_m`` (platforms merged by name)
  with its lines and the vehicles arriving on a weekday, in the morning peak and all day.
  Its ``weight`` (vehicles in the peak x seats per vehicle) is what campus.yaml uses to
  spread the commuting students over the stops (``population.dorm_share`` aside).
- **How long is a ride across campus?** For every pair of campus stops joined by a line
  without changing: trips per day, the shortest and the median in-vehicle time and the
  median headway. It is the transport the metro competes with (``transit/rides.csv``);
  every single ride (``transit/trips.parquet``) is what the simulation boards, and the
  instance's no-metro time is the faster of walking and the expected ride.

Feeds: ``transit.feeds`` in config.yaml (bus ``A``, tram ``T``), cached in data/raw/gtfs/.
Service days come from ``calendar.txt`` and ``calendar_dates.txt`` for ``transit.date``
(default: the first Tuesday from today that the feeds cover).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import re
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ..schemas.tables import TRANSIT_RIDES, TRANSIT_STOPS, TRANSIT_TRIPS

log = logging.getLogger(__name__)

DAY_START_S, DAY_END_S = 6 * 3600, 21 * 3600


def download(feeds: dict[str, str], raw_dir: Path, user_agent: str, refresh=False) -> dict:
    """mode -> local zip (downloaded once)."""
    out = {}
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for mode, url in feeds.items():
        f = raw_dir / Path(url).name
        if refresh or not f.exists():
            log.info("downloading %s", url)
            r = requests.get(url, timeout=300, headers={"User-Agent": user_agent})
            r.raise_for_status()
            f.write_bytes(r.content)
        out[mode] = f
    return out


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def seconds(hms: pd.Series) -> np.ndarray:
    parts = hms.str.split(":", expand=True).astype(int)
    return (parts[0] * 3600 + parts[1] * 60 + parts[2]).to_numpy()


def _read(z: zipfile.ZipFile, name: str, **kw) -> pd.DataFrame:
    if name not in z.namelist():
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(z.read(name)), dtype=str, keep_default_na=False, **kw)


def services_on(z: zipfile.ZipFile, date: dt.date) -> set[str]:
    day = date.strftime("%Y%m%d")
    on: set[str] = set()
    cal = _read(z, "calendar.txt")
    if len(cal):
        col = date.strftime("%A").lower()
        live = cal[(cal[col] == "1") & (cal["start_date"] <= day) & (cal["end_date"] >= day)]
        on |= set(live["service_id"])
    ex = _read(z, "calendar_dates.txt")
    if len(ex):
        ex = ex[ex["date"] == day]
        on |= set(ex.loc[ex["exception_type"] == "1", "service_id"])
        on -= set(ex.loc[ex["exception_type"] == "2", "service_id"])
    return on


def default_date(zips: dict[str, Path], today: dt.date | None = None) -> dt.date:
    """First Tuesday from ``today`` on which every feed runs some service."""
    d = today or dt.date.today()
    d += dt.timedelta(days=(1 - d.weekday()) % 7)
    for _ in range(26):
        if all(services_on(zipfile.ZipFile(f), d) for f in zips.values()):
            return d
        d += dt.timedelta(days=7)
    raise ValueError("the GTFS feeds run no service on any Tuesday of the next half year")


def campus_transit(
    zips: dict[str, Path], bbox: dict, date: dt.date, cfg: dict
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``tables.TRANSIT_STOPS``, ``TRANSIT_RIDES`` and ``TRANSIT_TRIPS`` for ``date``."""
    t = cfg.get("transit", {})
    seats = {k: float(v) for k, v in t.get("seats", {"bus": 90, "tram": 180}).items()}
    peak = [int(h) * 3600 for h in t.get("peak_hours", [7, 10])]
    margin = float(t.get("margin_m", 0.0))
    dlat = margin / 111_320.0
    dlon = dlat / np.cos(np.radians((bbox["south"] + bbox["north"]) / 2))
    west, east = bbox["west"] - dlon, bbox["east"] + dlon
    south, north = bbox["south"] - dlat, bbox["north"] + dlat

    events = []  # one row per (trip, campus platform) stop event
    platforms = []
    for mode, f in zips.items():
        z = zipfile.ZipFile(f)
        stops = _read(z, "stops.txt")
        lon, lat = stops["stop_lon"].astype(float), stops["stop_lat"].astype(float)
        inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
        st = stops[inside].assign(lon=lon[inside], lat=lat[inside], mode=mode)
        st["stop_id"] = mode + ":" + st["stop_id"]
        platforms.append(st[["stop_id", "stop_name", "lon", "lat", "mode"]])
        ids = set(stops.loc[inside, "stop_id"])
        trips = _read(z, "trips.txt", usecols=["route_id", "service_id", "trip_id"])
        trips = trips[trips["service_id"].isin(services_on(z, date))]
        routes = _read(z, "routes.txt", usecols=["route_id", "route_short_name"])
        trips = trips.merge(routes, on="route_id")
        chunks = []
        with z.open("stop_times.txt") as fh:
            for ch in pd.read_csv(
                fh,
                dtype=str,
                usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
                chunksize=1_000_000,
            ):
                chunks.append(ch[ch["stop_id"].isin(ids)])
        times = pd.concat(chunks).merge(trips[["trip_id", "route_short_name"]], on="trip_id")
        times["stop_id"] = mode + ":" + times["stop_id"]
        times["trip_id"] = mode + ":" + times["trip_id"]
        times["arr_s"] = seconds(times["arrival_time"])
        times["dep_s"] = seconds(times["departure_time"])
        times["seq"] = times["stop_sequence"].astype(int)
        times["mode"] = mode
        events.append(
            times[["trip_id", "stop_id", "seq", "arr_s", "dep_s", "route_short_name", "mode"]]
        )
    plat = pd.concat(platforms, ignore_index=True)
    ev = pd.concat(events, ignore_index=True)
    plat["campus_stop"] = "stop:" + plat["stop_name"].map(slug)
    ev = ev.merge(plat[["stop_id", "campus_stop"]], on="stop_id")

    # --- stops
    rows = []
    for sid, p in plat.groupby("campus_stop"):
        e = ev[ev["campus_stop"] == sid]
        am = e[(e["arr_s"] >= peak[0]) & (e["arr_s"] < peak[1])]
        day = e[(e["arr_s"] >= DAY_START_S) & (e["arr_s"] < DAY_END_S)]
        weight = float(am["mode"].map(lambda m: seats.get(m, 90.0)).sum())  # 90: unknown mode
        rows.append(
            {
                "stop_id": sid,
                "name": p["stop_name"].iloc[0],
                "lon": round(float(p["lon"].mean()), 6),
                "lat": round(float(p["lat"].mean()), 6),
                "modes": "|".join(sorted(set(p["mode"]))),
                "n_platforms": len(p),
                "lines": " ".join(sorted(set(e["route_short_name"]), key=_line_key)),
                "arrivals_peak": len(am),
                "arrivals_day": len(day),
                "headway_peak_s": round((peak[1] - peak[0]) / len(am)) if len(am) else None,
                "weight": round(weight / 1000.0, 2),
            }
        )
    stops_df = pd.DataFrame(rows).sort_values("weight", ascending=False).reset_index(drop=True)
    stops_df["headway_peak_s"] = stops_df["headway_peak_s"].astype("Int64")
    stops_df = stops_df[stops_df["arrivals_day"] > 0].reset_index(drop=True)
    TRANSIT_STOPS.validate(stops_df)

    # --- rides between campus stops on one trip
    ev = ev.sort_values(["trip_id", "seq"])
    ev = ev[(ev["dep_s"] >= DAY_START_S) & (ev["dep_s"] < DAY_END_S)]
    a = ev.merge(ev, on="trip_id", suffixes=("_a", "_b"))
    a = a[(a["seq_b"] > a["seq_a"]) & (a["campus_stop_a"] != a["campus_stop_b"])]
    a = a.assign(ride_s=a["arr_s_b"] - a["dep_s_a"])
    # a trip passing a stop twice: keep its shortest ride per pair (departure of that ride)
    a = (
        a.sort_values(["ride_s", "dep_s_a"])
        .drop_duplicates(["trip_id", "campus_stop_a", "campus_stop_b"])
        .rename(columns={"dep_s_a": "dep_s", "route_short_name_a": "line"})
        .sort_values(["trip_id", "campus_stop_a", "campus_stop_b"])[
            ["trip_id", "campus_stop_a", "campus_stop_b", "ride_s", "dep_s", "line"]
        ]
        .reset_index(drop=True)
    )
    rides = []
    for (fa, fb), g in a.groupby(["campus_stop_a", "campus_stop_b"]):
        dep = np.sort(g["dep_s"].to_numpy())
        rides.append(
            {
                "from_stop": fa,
                "to_stop": fb,
                "lines": " ".join(sorted(set(g["line"]), key=_line_key)),
                "trips_day": len(g),
                "min_ride_s": int(g["ride_s"].min()),
                "median_ride_s": int(g["ride_s"].median()),
                "median_headway_s": int(np.median(np.diff(dep))) if len(dep) > 1 else None,
            }
        )
    rides_df = pd.DataFrame(rides)
    if len(rides_df):
        rides_df["median_headway_s"] = rides_df["median_headway_s"].astype("Int64")
    TRANSIT_RIDES.validate(rides_df)
    trips_df = pd.DataFrame(
        {
            "from_stop": a["campus_stop_a"],
            "to_stop": a["campus_stop_b"],
            "line": a["line"],
            "dep_s": a["dep_s"].astype(int),
            "arr_s": (a["dep_s"] + a["ride_s"]).astype(int),
        }
    ).sort_values(["from_stop", "to_stop", "dep_s"])
    trips_df = trips_df.drop_duplicates(["from_stop", "to_stop", "dep_s", "arr_s"])
    trips_df = trips_df.reset_index(drop=True)
    TRANSIT_TRIPS.validate(trips_df)
    log.info(
        "transit %s: %d campus stops, %d stop pairs with a direct ride, %d rides",
        date, len(stops_df), len(rides_df), len(trips_df),
    )  # fmt: skip
    return stops_df, rides_df, trips_df


def _line_key(line: str):
    return (0, int(line), "") if line.isdigit() else (1, 0, line)


def campus_yaml_stops(stops: pd.DataFrame) -> str:
    """The ``stops:`` block for campus.yaml."""
    out = ["stops:"]
    for r in stops.itertuples():
        out += [
            f'  - id: "{r.stop_id}"',
            f"    name: {json.dumps(r.name, ensure_ascii=False)}",
            f"    location: [{r.lon}, {r.lat}]   # {r.modes}: {r.lines}",
            f"    weight: {max(r.weight, 0.01)}   # {r.arrivals_peak} vehicles in the peak (GTFS)",
        ]
    return "\n".join(out) + "\n"

"""Train timetable of a metro line (``simulation/metro/schedule.parquet``, section 9.1).

Runs leave every ``metro.headway_s`` between ``metro.service.start`` and ``end``, in both
directions:

- ``line`` A-B-C-D: direction +1 runs A -> D, direction -1 runs D -> A;
- ``loop`` A-B-C-D-A: direction +1 runs A -> B -> ... -> A, direction -1 the other way round.
  Trains go round and round: a run back at A leaves again after ``dwell_s``, like at any
  station, so departures are ``cycle / n`` apart (cycle = one round + dwell, n trains: the
  fewest that keep it within ``headway_s``) and a rider passing A only waits the dwell.

Trains run at ``metro.speed_mps`` on straight tunnels between platforms and stop
``metro.dwell_s`` at every station in between. A train that finishes a run takes the next
run leaving from that station (after ``dwell_s`` of turnaround), so ``train_id`` counts the
physical trains a day needs.
"""

import math

import numpy as np
import pandas as pd

from ..schemas.tables import METRO_SCHEDULE

DAY_S = 24 * 3600


def hhmm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60


def station_order(k: int, topology: str, direction: int) -> list[int]:
    """Indices of the stations one run visits, in order."""
    if topology == "loop":
        ring = list(range(k)) if direction == 1 else [0, *range(k - 1, 0, -1)]
        return [*ring, 0]
    return list(range(k)) if direction == 1 else list(range(k - 1, -1, -1))


def run_times(
    order: list[int], platforms: np.ndarray, speed: float, dwell: float
) -> list[tuple[float, float]]:
    """(arrive, depart) offsets from the run start for every stop of a run."""
    out = [(0.0, 0.0)]
    t = 0.0
    for a, b in zip(order, order[1:], strict=False):
        t += math.dist(platforms[a], platforms[b]) / speed
        out.append((t, t + dwell))
        t += dwell
    out[-1] = (out[-1][0], out[-1][0])  # no dwell at the end of the run
    return out


def build_schedule(
    stations: list[str],
    platforms: np.ndarray,
    topology: str,
    cfg: dict,
    weekdays: list[int] | None = None,
) -> pd.DataFrame:
    """Every stop of every run in the modelled week. ``platforms``: (k, 2) or (k, 3)
    positions in metres, in line order."""
    m = cfg["metro"]
    speed, dwell, headway = float(m["speed_mps"]), float(m["dwell_s"]), float(m["headway_s"])
    start, end = hhmm(m["service"]["start"]), hhmm(m["service"]["end"])
    weekdays = weekdays or list(cfg.get("simulation", {}).get("weekdays", [1, 2, 3, 4, 5]))
    k = len(stations)
    plans = {
        d: (order := station_order(k, topology, d), run_times(order, platforms, speed, dwell))
        for d in (1, -1)
    }
    if topology == "loop":  # continuous service: see the module docstring
        cycle = plans[1][1][-1][0] + dwell
        headway = cycle / math.ceil(cycle / headway)
    rows = []
    run_id = 0
    for day in weekdays:
        base = (day - 1) * DAY_S
        starts = np.arange(start, end + 1e-6, headway)
        departures = [(float(t), d) for t in starts for d in (1, -1)]  # +1 first at equal times
        free: list[tuple[float, int, int]] = []  # (free at, station, train) of finished runs
        n_trains = 0
        for t0, d in departures:
            order, offsets = plans[d]
            first = order[0]
            # a tolerance: a loop's departures are a float headway apart, and the train back
            # exactly on time must not miss its next round by a rounding error
            ready = [f for f in free if f[1] == first and f[0] <= t0 + 1e-6]
            if ready:
                f = min(ready)
                free.remove(f)
                train = f[2]
            else:
                train = n_trains
                n_trains += 1
            for seq, (station, (arr, dep)) in enumerate(zip(order, offsets, strict=True)):
                rows.append(
                    (run_id, train, day, d, seq, stations[station],
                     round(base + t0 + arr), round(base + t0 + dep))
                )  # fmt: skip
            free.append((t0 + offsets[-1][1] + dwell, order[-1], train))
            run_id += 1
    df = pd.DataFrame(rows, columns=METRO_SCHEDULE.column_names)
    METRO_SCHEDULE.validate(df)
    return df

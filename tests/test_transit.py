"""GTFS -> campus stops and direct rides, on a two-line synthetic feed."""

import datetime as dt
import zipfile

from metro_agh.schemas.tables import TRANSIT_RIDES, TRANSIT_STOPS, TRANSIT_TRIPS
from metro_agh.transit.gtfs import campus_transit, campus_yaml_stops, default_date, slug

BBOX = {"west": 19.90, "south": 50.06, "east": 19.93, "north": 50.08}


def feed(path, rows_stop_times: list[str], service_dates: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "1,Czarnowiejska,50.0664,19.9226\n"
            "2,Czarnowiejska,50.0663,19.9227\n"
            "3,Miasteczko Studenckie AGH,50.0699,19.9050\n"
            "4,Daleko,50.2000,20.1000\n",
        )
        z.writestr("routes.txt", "route_id,route_short_name\nr1,164\nr2,999\n")
        z.writestr(
            "trips.txt",
            "route_id,service_id,trip_id\nr1,wd,t1\nr1,wd,t2\nr1,sun,t3\nr2,wd,t4\n",
        )
        z.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            + "\n".join(rows_stop_times)
            + "\n",
        )
        z.writestr(
            "calendar_dates.txt",
            "service_id,date,exception_type\n" + "\n".join(f"wd,{d},1" for d in service_dates),
        )


def test_campus_stops_and_rides(tmp_path):
    f = tmp_path / "bus.zip"
    feed(
        f,
        [
            "t1,07:30:00,07:30:00,1,1",
            "t1,07:34:00,07:35:00,3,2",
            "t2,08:00:00,08:00:00,2,1",
            "t2,08:06:00,08:06:00,3,2",
            "t3,07:00:00,07:00:00,1,1",  # Sunday service: not on the chosen day
            "t4,09:00:00,09:00:00,4,1",  # outside the bbox
        ],
        ["20261013"],
    )
    cfg = {"transit": {"peak_hours": [7, 10], "seats": {"bus": 90}}}
    stops, rides, trips = campus_transit({"bus": f}, BBOX, dt.date(2026, 10, 13), cfg)
    TRANSIT_TRIPS.validate(trips)
    assert list(zip(trips["dep_s"], trips["arr_s"], strict=True)) == [
        (7 * 3600 + 30 * 60, 7 * 3600 + 34 * 60),
        (8 * 3600, 8 * 3600 + 6 * 60),
    ]
    TRANSIT_STOPS.validate(stops)
    TRANSIT_RIDES.validate(rides)
    s = stops.set_index("stop_id")
    assert set(s.index) == {"stop:czarnowiejska", "stop:miasteczko_studenckie_agh"}
    assert s.loc["stop:czarnowiejska", "n_platforms"] == 2
    assert s.loc["stop:czarnowiejska", "arrivals_peak"] == 2
    assert s.loc["stop:czarnowiejska", "headway_peak_s"] == 3 * 3600 // 2
    assert s.loc["stop:czarnowiejska", "lines"] == "164"
    r = rides.set_index(["from_stop", "to_stop"]).loc[
        ("stop:czarnowiejska", "stop:miasteczko_studenckie_agh")
    ]
    assert (r["trips_day"], r["min_ride_s"], r["median_ride_s"]) == (2, 240, 300)
    assert r["median_headway_s"] == 1800
    assert "stop:czarnowiejska" in campus_yaml_stops(stops)


def test_default_date_is_a_served_tuesday(tmp_path):
    f = tmp_path / "bus.zip"
    feed(f, ["t1,07:30:00,07:30:00,1,1"], ["20261020"])
    assert default_date({"bus": f}, today=dt.date(2026, 10, 12)) == dt.date(2026, 10, 20)


def test_slug():
    assert slug("Plac Inwalidów") == "plac_inwalidow"
    assert slug("AGH / UR") == "agh_ur"
    assert slug("Cichy Kącik") == "cichy_kacik"
    assert slug("Łobzów") == "lobzow"

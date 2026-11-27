"""Lenses that play over time (timelapse.json, lazy): tourist nights by month, the presidential vote morph and the
population years, for the shared motion clock.

* tourism: nights in tourist accommodation per voivodeship for each of the newest 36 months (GUS BDL P2882), with
  nights per resident (population on 31 December 2025). Values are listed in world.json `states` order, so a hex
  takes the value of its voivodeship (`owner`).
* elections: the three presidential runoffs drawn by the lenses vote_2015, vote_2020 and vote (2025). They share one
  scale and one meaning (the right-wing candidate's share), so the browser can blend the colours of two runoffs;
  only the runoff years carry numbers.
* population: the density and change lenses already play from timeline.json; this block names that file and its
  first and last dates.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web

REQUIRES = ["_world", "pl_tourism_monthly", "pl_stats_population", "pl_soc_elections", "lenses.json", "timeline.json"]
PRODUCES = ["timelapse.json"]

POPULATION_DATE = "2025-12-31"
# (lens id, year, runoff date, interim table, winner field, other field). The winner of each runoff is the candidate
# whose share the lens draws.
RUNOFFS = [
    ("vote_2015", 2015, "2015-05-24", "president_2015_r2_totals", "duda", "komorowski"),
    ("vote_2020", 2020, "2020-07-12", "president_2020_r2_totals", "duda", "trzaskowski"),
    ("vote", 2025, "2025-06-01", "president_2025_r2_totals", "nawrocki", "trzaskowski"),
]
NAMES = {"duda": "Andrzej Duda", "komorowski": "Bronisław Komorowski", "trzaskowski": "Rafał Trzaskowski",
         "nawrocki": "Karol Nawrocki"}


def tourism_block(interim: dict, states: list[str], population: dict[str, float | None]) -> dict:
    table = interim["tables"]["nights_monthly"]
    months = interim["months"]
    nights, per = [], []
    for m in months:
        key = f"nights_{m.replace('-', '_')}"
        row = [(table["rows"].get(s) or {}).get(key) for s in states]
        nights.append(row)
        per.append([None if v is None or not population.get(s) else round(v / population[s], 3)
                    for v, s in zip(row, states)])
    national = [None if any(v is None for v in r) else sum(r) for r in nights]
    return {
        "axis": "month",
        "months": months,
        "nights": nights,
        "per_resident": per,
        "national": national,
        "population": [population.get(s) for s in states],
        "population_date": POPULATION_DATE,
    }


def frac(pct: float | None) -> float | None:
    """Interim percent (0..100) -> web share (0..1)."""
    return None if pct is None else round(pct / 100, 4)


def elections_block(lenses: dict, elections: dict) -> dict:
    by_id = {l["id"]: l for l in lenses["lenses"]}
    frames = []
    for lid, year, day, table, win, other in RUNOFFS:
        lens = by_id.get(lid)
        totals = ((elections.get("tables") or {}).get(table) or {}).get("rows", {}).get("PL") or {}
        frames.append({
            "year": year, "date": day, "lens": lid if lens else None,
            "candidate": NAMES[win], "opponent": NAMES[other],
            "share": frac(totals.get(f"{win}_share")), "turnout": frac(totals.get("turnout")),
        })
    return {"axis": "year", "frames": frames}


def population_block(timeline: dict) -> dict:
    dates = timeline.get("dates") or []
    return {"axis": "year", "file": "timeline.json", "lenses": ["density", "growth"],
            "first": dates[0] if dates else None, "last": dates[-1] if dates else None}


def build() -> None:
    world = load_interim("_world")
    states = world["states"]
    tourism = load_interim_payload("pl_tourism_monthly")
    pop_rows = load_interim("pl_stats_population")["tables"]["demographic_indicators"]["rows"]
    population = {s: (pop_rows.get(s) or {}).get("population") for s in states}
    elections = load_interim_payload("pl_soc_elections")
    lenses = json.loads((WEB_DATA / "lenses.json").read_text())
    timeline = json.loads((WEB_DATA / "timeline.json").read_text())
    tour = tourism_block(tourism["data"], states, population)
    write_web("timelapse.json", {
        "version": 1,
        "vintage": {"tourism": tourism.get("vintage"), "elections": elections.get("vintage"),
                    "population": timeline.get("vintage")},
        "sources": ["pl_tourism_monthly", "pl_stats_population", "pl_soc_elections", "pl_hist_population"],
        "states": states,
        "tourism": tour,
        "elections": elections_block(lenses, elections["data"]),
        "population": population_block(timeline),
        "rules": [
            "Tourist nights by month: nights in tourist accommodation with 10 or more beds in each voivodeship, "
            "divided by its population on 31 December 2025; every hex shows its voivodeship.",
            "Presidential vote over time: the runoffs of 2015, 2020 and 2025 on one scale, the winner's share of "
            "valid votes; between two runoffs the map blends their colours and shows numbers only for runoff years.",
        ],
    })
    print(f"    tourism {len(tour['months'])} months x {len(states)} voivodeships")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "timelapse.json"
    if not path.exists():
        return [("NOTE", "timelapse.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    states = doc.get("states") or []
    world = Path(web_dir) / "world.json"
    if world.exists():
        w = json.loads(world.read_text())
        if [s.get("fips") for s in w.get("states", [])] != states:
            out.append(("FAIL", "timelapse.json: states must follow world.json states"))
    t = doc.get("tourism") or {}
    months = t.get("months") or []
    for key in ("nights", "per_resident"):
        arr = t.get(key) or []
        if len(arr) != len(months) or any(len(r) != len(states) for r in arr):
            out.append(("FAIL", f"timelapse.json tourism.{key}: one row per month, one value per voivodeship"))
    if any(v is not None and v < 0 for r in t.get("nights") or [] for v in r):
        out.append(("FAIL", "timelapse.json tourism: negative nights"))
    if months:
        filled = sum(v is not None for r in t.get("nights") or [] for v in r)
        out.append(("PASS", f"timelapse.json tourism: {len(months)} months ({months[0]} to {months[-1]}) x "
                            f"{len(states)} voivodeships, {filled} values"))
    lenses_path = Path(web_dir) / "lenses.json"
    frames = (doc.get("elections") or {}).get("frames") or []
    if lenses_path.exists() and frames:
        by_id = {l["id"]: l for l in json.loads(lenses_path.read_text()).get("lenses", [])}
        used = [by_id.get(f.get("lens")) for f in frames]
        if any(l is None for l in used):
            out.append(("FAIL", "timelapse.json elections: a frame names a lens missing from lenses.json"))
        elif len({(tuple(l.get("ramp") or []), tuple(l.get("domain") or []), l.get("scale")) for l in used}) != 1:
            out.append(("FAIL", "timelapse.json elections: the runoff lenses must share ramp, domain and scale"))
        else:
            out.append(("PASS", f"timelapse.json elections: {len(frames)} runoffs on one scale "
                                f"({', '.join(str(f['year']) for f in frames)})"))
    return out

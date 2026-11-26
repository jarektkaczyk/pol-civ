"""Shared loading of the Polish statistics interims for the people and economy builders (a helper, not a builder).

Every statistics table is optional: a missing interim or table reads as an empty dict, so the builders write null
for its fields and pick the data up on the next rebuild.

Units: gmina = TERYT7 (with the type digit), powiat = TERYT4, voivodeship = TERYT2 (see docs/BLUEPRINT.md section 5).
"""

from __future__ import annotations

import math

from ..core.store import load_interim_payload

STATS_SOURCES = [
    "pl_stats_population", "pl_stats_labour", "pl_stats_prosperity", "pl_gdp", "pl_foreigners", "pl_census_2021",
    "pl_soc_elections", "pl_soc_faith", "pl_soc_air", "pl_soc_health", "pl_soc_universities", "pl_soc_disasters",
    "pl_geo_fua", "pl_geo_places",
]


def optional(name: str) -> dict | None:
    """The interim payload {vintage, data, ...}, or None when the source has not been processed yet."""
    try:
        return load_interim_payload(name)
    except FileNotFoundError:
        print(f"    ! interim {name} missing: its fields stay null")
        return None


class Stats:
    """All optional statistics interims, with table lookups that never fail."""

    def __init__(self, names=STATS_SOURCES, loader=optional):
        self.payload = {n: loader(n) for n in names}
        self.by6: dict[str, str] | None = None
        self._rekeyed: dict = {}

    def rekey(self, units: "Units") -> "Stats":
        """Key every gmina-level table by the current TERYT7 code. Some sources still carry a gmina's old type
        digit (0601052 for 0601053): the first six digits identify the gmina, so they are matched on those."""
        self.by6 = units.by6
        self._rekeyed = {}
        return self

    def gmina_key(self, code: str) -> str:
        return self.by6.get(str(code)[:6], code) if self.by6 else code

    def data(self, source: str) -> dict:
        p = self.payload.get(source)
        return (p or {}).get("data") or {}

    def has(self, source: str, table: str | None = None) -> bool:
        d = self.data(source)
        return bool(d) and (table is None or bool(self.rows(source, table)))

    def table(self, source: str, name: str) -> dict:
        return (self.data(source).get("tables") or {}).get(name) or {}

    def rows(self, source: str, name: str) -> dict:
        t = self.table(source, name)
        rows = t.get("rows") or {}
        if self.by6 and t.get("level") == "gmina":
            key = (source, name)
            if key not in self._rekeyed:
                self._rekeyed[key] = {self.gmina_key(k): v for k, v in rows.items()}
            return self._rekeyed[key]
        return rows

    def value(self, source: str, name: str, code: str, field: str):
        return (self.rows(source, name).get(code) or {}).get(field)

    def field_year(self, source: str, name: str, field: str):
        return ((self.table(source, name).get("fields") or {}).get(field) or {}).get("year")

    def field_date(self, source: str, name: str, field: str) -> str | None:
        """The '30 June 2026' phrase at the start of a field's note, if any."""
        import re

        note = ((self.table(source, name).get("fields") or {}).get(field) or {}).get("note") or ""
        m = re.match(r"(\d{1,2} [A-Z][a-z]+ \d{4})", note)
        return m.group(1) if m else None

    def vintage(self, source: str) -> str | None:
        p = self.payload.get(source)
        return (p or {}).get("vintage") or (p or {}).get("data", {}).get("vintage")

    def used(self) -> list[str]:
        return [n for n, p in self.payload.items() if p]


def num(v) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def ratio(a, b, scale: float = 1.0, digits: int | None = None) -> float | None:
    a, b = num(a), num(b)
    if a is None or not b:
        return None
    v = a / b * scale
    return round(v, digits) if digits is not None else v


def total(values) -> float | None:
    """Sum of the values, or None when every value is None (a None among numbers is skipped)."""
    vals = [num(v) for v in values]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def full_sum(values) -> float | None:
    """Sum of the values, or None when any of them is None (an exact total or nothing)."""
    vals = [num(v) for v in values]
    return None if not vals or any(v is None for v in vals) else sum(vals)


def median_from_groups(groups: list[tuple[float, float | None, float]]) -> float | None:
    """Median age from 5-year groups [(lower age, upper age or None for open, count)], by linear interpolation
    inside the group that holds the middle person (the usual demographic method). None if a count is missing or
    the median falls in the open-ended top group."""
    if any(num(c) is None for _, _, c in groups):
        return None
    n = sum(c for _, _, c in groups)
    if n <= 0:
        return None
    half, acc = n / 2, 0.0
    for lo, hi, c in groups:
        if acc + c >= half and c > 0:
            if hi is None:
                return None
            return round(lo + (half - acc) / c * (hi - lo), 1)
        acc += c
    return None


AGE_GROUPS = [(a, a + 5, f"age_{a}_{a + 4}") for a in range(0, 85, 5)] + [(85, None, "age_85_plus")]


def median_age(rec: dict) -> float | None:
    return median_from_groups([(lo, hi, rec.get(k)) for lo, hi, k in AGE_GROUPS]) if rec else None


class Units:
    """Gminas, powiaty and voivodeships of the map (the _world interim order) with names from TERYT 2026."""

    def __init__(self, world: dict, teryt: dict):
        self.gminas: list[str] = list(world["counties"])
        self.index = {g: i for i, g in enumerate(self.gminas)}
        self.voivodeships: list[str] = list(world["states"])
        self.powiaty: list[str] = list(world["powiaty"])
        self.gmina_name = {g["code"]: g["name"] for g in teryt["gminy"]}
        self.gmina_type = {g["code"]: g.get("type") for g in teryt["gminy"]}
        self.powiat_name = {p["code"]: p["name"] for p in teryt["powiaty"]}
        self.voiv_name = {v["code"]: v["name"] for v in teryt["voivodeships"]}
        self.gminas_of_powiat: dict[str, list[str]] = {}
        for g in self.gminas:
            self.gminas_of_powiat.setdefault(g[:4], []).append(g)
        self.by6 = {g[:6]: g for g in self.gminas}

    def powiat_label(self, code: str) -> str:
        """'Powiat m. Kraków' -> 'Kraków (city)', 'Powiat bolesławiecki' -> 'powiat bolesławiecki'."""
        name = self.powiat_name.get(code, code)
        if name.startswith("Powiat m. st. "):
            return name[len("Powiat m. st. "):] + " (city)"
        if name.startswith("Powiat m. "):
            return name[len("Powiat m. "):] + " (city)"
        return name[0].lower() + name[1:] if name.startswith("Powiat") else name


def cell_weights(world: dict, gmina_pop: list[float | None], extra: dict[int, int] | None = None
                 ) -> list[list[tuple[int, float]]]:
    """Per cell: [(gmina index, people)] where each gmina's population is shared over its sample hits.

    `extra` = {gmina index: cell} places a gmina that no sample hits (smaller than the sample spacing, see
    `_world.gminy_without_samples`) whole in the cell under its centre."""
    samples = world["county_samples"]
    hits: dict[int, int] = {}
    for s in samples:
        for k in s:
            if k >= 0:
                hits[k] = hits.get(k, 0) + 1
    out: list[list[tuple[int, float]]] = [[] for _ in samples]
    for i, s in enumerate(samples):
        seen: dict[int, int] = {}
        for k in s:
            if k >= 0:
                seen[k] = seen.get(k, 0) + 1
        out[i] = [(k, (gmina_pop[k] or 0) * n / hits[k]) for k, n in seen.items()]
    for k, cell in (extra or {}).items():
        if k not in hits and 0 <= cell < len(out):
            out[cell].append((k, gmina_pop[k] or 0))
    return out


def unsampled_cells(world: dict, lau: dict | None, proj, grid) -> dict[int, int]:
    """{gmina index: Polish land cell under its LAU outline's centre} for the gminas no hex sample hits."""
    hits = {k for s in world["county_samples"] for k in s if k >= 0}
    by6 = {g[:6]: i for i, g in enumerate(world["counties"]) if i not in hits}
    out = {}
    for g in (lau or {}).get("gminy", []):
        i = by6.get(g.get("teryt6"))
        if i is None or not g.get("rings"):
            continue
        ring = max(g["rings"], key=len)
        lon = sum(p[0] for p in ring) / len(ring)
        lat = sum(p[1] for p in ring) / len(ring)
        cell = grid.cell_at(*proj(lon, lat))
        if cell >= 0 and world["owner"][cell] >= 0:
            out[i] = cell
    return out


def spread(weights, values: list, digits: int | None = None) -> list:
    """Population-weighted mean of the gmina values over each cell's parts (None where no part has a value).
    A cell whose parts all have 0 people takes the plain mean."""
    out = [None] * len(weights)
    for i, parts in enumerate(weights):
        vals = [(values[k], p) for k, p in parts if values[k] is not None]
        if not vals:
            continue
        w = sum(p for _, p in vals)
        v = sum(x * p for x, p in vals) / w if w > 0 else sum(x for x, _ in vals) / len(vals)
        out[i] = round(v, digits) if digits is not None else v
    return out

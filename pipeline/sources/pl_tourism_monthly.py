"""GUS BDL: nights spent in tourist accommodation by voivodeship and month, the newest 36 months.

BDL subject P2882 ("Wykorzystanie turystycznych obiektow noclegowych wedlug miesiecy") holds one variable per
calendar month and measure. This source reads the variable list, picks "udzielone noclegi ogolem" in "turystyczne
obiekty noclegowe ogolem" (all nights, all establishments with 10 or more beds) for each month, and downloads
those 12 variables at voivodeship level for the years that cover the newest 36 published months: 16 BDL requests
in all (4 variable-list pages, 12 data requests).
"""

from __future__ import annotations

from datetime import date

from ..core.bdl import bdl_url, download_pages, load_pages, teryt_from_bdl, UNQUALIFIED_ATTRIBUTES
from ..core.source import Source, SourceInfo

SUBJECT = "P2882"
ESTABLISHMENTS = "turystyczne obiekty noclegowe ogółem"
MEASURE = "udzielone noclegi ogółem"
MONTHS_PL = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
             "październik", "listopad", "grudzień"]
N_MONTHS = 36
LICENCE = "Statistics Poland (GUS), Creative Commons Attribution 4.0."
METADATA = "https://bdl.stat.gov.pl/bdl/metadane/cechy/2882"


def years_needed(today: date, n_months: int = N_MONTHS) -> list[int]:
    """Calendar years that can hold the newest `n_months` months published before `today`. GUS publishes a month
    about two months after it ends, so the window starts at most n_months + 4 months before today."""
    back = today.year * 12 + today.month - 1 - (n_months + 4)
    return list(range(back // 12, today.year + 1))


def month_variables(variables: list[dict]) -> dict[int, int]:
    """BDL variable list of P2882 -> {month 1..12: variable id} for all nights in all establishments."""
    out = {}
    for v in variables:
        if v.get("n2") == ESTABLISHMENTS and v.get("n3") == MEASURE and v.get("n1") in MONTHS_PL:
            month = MONTHS_PL.index(v["n1"]) + 1
            if month in out:
                raise RuntimeError(f"BDL {SUBJECT}: two variables for {v['n1']}")
            out[month] = v["id"]
    if len(out) != 12:
        raise RuntimeError(f"BDL {SUBJECT}: found nights variables for {len(out)} of 12 months")
    return out


def monthly_rows(records_by_month: dict[int, list[dict]]) -> dict[str, dict[str, float | None]]:
    """{month: BDL records} -> {"YYYY-MM": {voivodeship code: nights or None}}. Qualified values stay None."""
    out: dict[str, dict[str, float | None]] = {}
    for month, records in records_by_month.items():
        for rec in records:
            code = teryt_from_bdl(rec["id"], 2)
            for item in rec.get("values") or []:
                key = f"{int(item['year']):04d}-{month:02d}"
                val = item.get("val", item.get("value"))
                attr = item.get("attrId")
                ok = isinstance(val, (int, float)) and not isinstance(val, bool) and (
                    attr is None or attr in UNQUALIFIED_ATTRIBUTES)
                out.setdefault(key, {})[code] = val if ok else None
    return out


def newest_months(rows: dict[str, dict[str, float | None]], n: int = N_MONTHS, units: int = 16) -> list[str]:
    """The newest `n` consecutive months, ending at the newest month that has a value for every voivodeship."""
    full = sorted(m for m, r in rows.items() if sum(v is not None for v in r.values()) == units)
    if not full:
        raise RuntimeError("no month with values for every voivodeship")
    y, m = map(int, full[-1].split("-"))
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    out.reverse()
    missing = [k for k in out if k not in rows]
    if missing:
        raise RuntimeError(f"months missing from the BDL download: {missing}")
    return out


class PlTourismMonthly(Source):
    info = SourceInfo(
        id="pl_tourism_monthly",
        title="Tourist accommodation: nights by voivodeship and month",
        publisher="Główny Urząd Statystyczny (GUS), Bank Danych Lokalnych",
        homepage=METADATA,
        license="CC BY 4.0",
        description="Nights spent by tourists in tourist accommodation with 10 or more beds, per voivodeship and "
        "calendar month (BDL subject P2882).",
        used_for=["Tourist nights by month lens"],
    )

    def _dir(self, variable: int) -> str:
        years = years_needed(self._today())
        return f"bdl/nights-{variable}-2-{years[0]}-{years[-1]}"

    @staticmethod
    def _today() -> date:
        return date(2026, 11, 27)  # run date of this vintage; bump it on a refresh

    def fetch(self, force: bool = False) -> None:
        download_pages(self, "variables", f"bdl/variables-{SUBJECT}", {"subject-id": SUBJECT}, force=force)
        variables = month_variables(load_pages(self.raw_dir, f"bdl/variables-{SUBJECT}"))
        for variable in variables.values():
            download_pages(self, f"data/by-variable/{variable}", self._dir(variable),
                           {"unit-level": 2, "year": years_needed(self._today())}, force=force)

    def process(self) -> dict:
        variables = month_variables(load_pages(self.raw_dir, f"bdl/variables-{SUBJECT}"))
        records = {m: load_pages(self.raw_dir, self._dir(v)) for m, v in variables.items()}
        rows = monthly_rows(records)
        months = newest_months(rows)
        codes = sorted({c for r in rows.values() for c in r})
        fields = {}
        for key in months:
            fields[f"nights_{key.replace('-', '_')}"] = {
                "label": f"Nights in tourist accommodation, {key}",
                "unit": "nights",
                "year": int(key[:4]),
                "note": f"{key}, establishments with 10 or more beds.",
            }
        table = {code: {f"nights_{k.replace('-', '_')}": rows[k].get(code) for k in months} for code in codes}
        files = [f"bdl/variables-{SUBJECT}/{p.name}" for p in sorted((self.raw_dir / f"bdl/variables-{SUBJECT}").glob("page-*.json"))]
        for v in variables.values():
            files += [f"{self._dir(v)}/{p.name}" for p in sorted((self.raw_dir / self._dir(v)).glob("page-*.json"))]
        example = bdl_url(f"data/by-variable/{variables[1]}", {"unit-level": 2, "year": years_needed(self._today())})
        return {
            "vintage": f"GUS BDL monthly tourism, {months[0]} to {months[-1]}",
            "months": months,
            "variables": {f"{m:02d}": v for m, v in sorted(variables.items())},
            "tables": {"nights_monthly": {"level": "voivodeship", "fields": fields, "rows": table}},
            "notes": [
                f"BDL subject {SUBJECT}, one variable per calendar month: nights given ('udzielone noclegi ogółem') "
                f"in all tourist accommodation establishments. Example request (January): {example}.",
                "Establishments with 10 or more beds. GUS publishes a month about two months after it ends.",
                "BDL values with a qualifying flag (provisional, confidential, missing) stay null.",
                LICENCE,
            ],
            "_files": files,
        }

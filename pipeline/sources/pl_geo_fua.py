"""Eurostat functional urban areas (FUA) of Poland and their member gminas (LAU).

Eurostat's LAU-NUTS correspondence workbook lists every LAU with the city and FUA it belongs to. For Poland the
LAU code is the GUS statistical unit id without its last digit, so the TERYT voivodeship, powiat and gmina
numbers (6 digits) are read from it and matched to the 2026 TERYT7 codes by the builders.
"""

from __future__ import annotations

from ..core.source import Source, SourceInfo
from ._pl_xlsx import read_xlsx, sheet_names

YEAR = 2025
URL = ("https://ec.europa.eu/eurostat/documents/345175/501971/EU-27-LAU-2025-NUTS-2024.xlsx/"
       "574c9e4a-2dae-99fe-5510-3fd18d8e90c2?t=1771601900130")
FILE = f"EU-27-LAU-{YEAR}-NUTS-2024.xlsx"


def teryt6_of_lau(lau: str) -> str | None:
    """Polish LAU code -> TERYT 6 digits (voivodeship, powiat, gmina numbers), or None.

    The workbook uses the GISCO form: '10' + region 2 + voivodeship 2 + subregion 2 + powiat 3 + gmina 2
    (Krakow: 1001121216101 -> 126101). The 11-digit form without '10' and a TERYT7 code are accepted too.
    """
    s = str(lau).strip()
    if s.startswith("PL_"):
        s = s[3:]
    if not s.isdigit():
        return None
    if len(s) == 13 and s.startswith("10"):  # GISCO form: 10 + region 2 + voiv 2 + subregion 2 + powiat 3 + gmina 2
        return s[4:6] + s[9:11] + s[11:13]
    if len(s) == 11:  # region 2 + voiv 2 + subregion 2 + powiat 3 + gmina 2
        return s[2:4] + s[7:9] + s[9:11]
    if len(s) == 7:  # TERYT7
        return s[:6]
    return None


def find_header(rows: list[list], *names: str) -> tuple[int, dict[str, int]]:
    """(row index, {wanted name: column}) of the first row holding every wanted header (case-insensitive prefix)."""
    for i, row in enumerate(rows[:20]):
        cells = [str(c or "").strip().upper() for c in row]
        cols = {}
        for n in names:
            hit = [j for j, c in enumerate(cells) if c == n.upper()] or [j for j, c in enumerate(cells) if c.startswith(n.upper())]
            if hit:
                cols[n] = hit[0]
        if len(cols) == len(names):
            return i, cols
    raise ValueError(f"header row with {names} not found")


class PlGeoFua(Source):
    info = SourceInfo(
        id="pl_geo_fua",
        title=f"Functional urban areas: LAU {YEAR} to city and FUA correspondence",
        publisher="Eurostat",
        homepage="https://ec.europa.eu/eurostat/web/nuts/local-administrative-units",
        license="Eurostat: free reuse with attribution (Eurostat copyright and licence policy)",
        description="The Eurostat list of local administrative units with the city and the functional urban area "
        "(FUA: a city plus its commuting zone) each one belongs to. Used for the Polish metros.",
        used_for=["Metros (FUA) of the City View and the Explorer"],
    )

    def fetch(self, force=False):
        self.download(URL, FILE, force=force, expect_binary=True)

    def process(self):
        path = self.raw_dir / FILE
        names = sheet_names(path)
        sheet = next((n for n in names if n.strip().upper() == "PL"), None)
        if sheet is None:
            raise ValueError(f"no PL sheet in {FILE}: {names}")
        rows = read_xlsx(path, sheet)
        h, col = find_header(rows, "NUTS3", "LAU CODE", "LAU NAME NATIONAL", "FUA ID", "FUA_NAME", "CITY ID", "CITY NAME")
        fuas: dict[str, dict] = {}
        gminas: dict[str, dict] = {}
        unmapped = []
        for row in rows[h + 1:]:
            if len(row) <= max(col.values()):
                row = row + [None] * (max(col.values()) + 1 - len(row))
            lau = row[col["LAU CODE"]]
            if lau in (None, ""):
                continue
            t6 = teryt6_of_lau(str(lau))
            if t6 is None:
                unmapped.append(str(lau))
                continue
            fua = str(row[col["FUA ID"]] or "").strip()
            city = str(row[col["CITY ID"]] or "").strip()
            fua = fua if fua and fua.upper() not in ("NO", "N/A", "NA") else None
            city = city if city and city.upper() not in ("NO", "N/A", "NA") else None
            gminas[t6] = {"lau": str(lau), "name": row[col["LAU NAME NATIONAL"]], "nuts3": row[col["NUTS3"]], "fua": fua,
                          "city": city}
            if fua:
                f = fuas.setdefault(fua, {"name": str(row[col["FUA_NAME"]] or "").strip(), "gminas": [], "cities": []})
                f["gminas"].append(t6)
                if city and city not in f["cities"]:
                    f["cities"].append(city)
        for f in fuas.values():
            f["gminas"].sort()
        print(f"    {len(gminas)} Polish LAU rows, {len(fuas)} FUAs, {sum(1 for g in gminas.values() if g['fua'])} in a FUA")
        return {
            "vintage": f"LAU {YEAR} (NUTS 2024) correspondence",
            "_files": [FILE],
            "year": YEAR,
            "fuas": fuas,
            "gminas": gminas,
            "notes": [
                "nuts3 is the NUTS 2024 subregion of the LAU.",
            "gminas are keyed by TERYT 6 digits (no type digit); builders add the type digit from TERYT 2026.",
                f"{len(unmapped)} LAU codes could not be read as TERYT" + (f": {unmapped[:5]}" if unmapped else ""),
            ],
        }

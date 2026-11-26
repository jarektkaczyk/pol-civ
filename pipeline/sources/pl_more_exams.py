"""Nationwide September 2026 school-location tables from the official exam map."""

from __future__ import annotations

from collections import defaultdict

from ..core.source import Source, SourceInfo
from ._pl_xlsx import read_xlsx
from .pl_soc_common import num, slug
from .pl_stats_population import AREA_FILE, AREA_URL, _area

HOMEPAGE = "https://mapa.wyniki.edu.pl/MapaEgzaminow/"
E8_FILE = "E8_2026_gminy_09.xlsx"
MATURA_FILE = "EM2023_2026_powiaty_09.xlsx"
FILES = {
    E8_FILE: HOMEPAGE + "assets/data/CSV/E8/2026/" + E8_FILE,
    MATURA_FILE: HOMEPAGE + "assets/data/CSV/EM2023/2026/" + MATURA_FILE,
}
E8_SUBJECTS = {
    "jezyk_polski": "e8_polish_mean_pct",
    "matematyka": "e8_math_mean_pct",
    "jezyk_angielski": "e8_english_mean_pct",
}


def _percentage(value):
    number = num(value)
    if number is not None and not 0 <= number <= 100:
        raise ValueError(f"Invalid exam percentage: {value!r}")
    return number


def parse_e8(rows, current_codes):
    """Keep publisher means, or weight the disjoint town and rural parts by candidates."""
    subjects, headings, *data = rows
    headings = [slug(value or "") for value in headings]
    code_col = headings.index("kod_teryt_gminy")
    columns = {}
    for i, subject in enumerate(subjects):
        key = E8_SUBJECTS.get(slug(subject or ""))
        if key is not None and headings[i:i + 2] == ["liczba_zdajacych", "wynik_sredni"]:
            columns[key] = (i, i + 1)
    if set(columns) != set(E8_SUBJECTS.values()):
        raise ValueError("Missing expected E8 exam columns")

    by_prefix = {code[:6]: code for code in current_codes}
    grouped = defaultdict(dict)
    unmatched = set()
    recoded = set()
    for row in data:
        raw = str(row[code_col] or "").strip()
        if not raw.isascii() or not raw.isdigit():
            continue
        raw = raw.zfill(7)
        code = by_prefix.get(raw[:6])
        if code is None or raw[-1] not in "12345":
            unmatched.add(raw)
            continue
        if raw != code and raw[-1] in "123":
            recoded.add((raw, code))
        if raw in grouped[code]:
            raise ValueError(f"Duplicate E8 area {raw}")
        grouped[code][raw] = {
            key: (num(row[count_col]), _percentage(row[mean_col]))
            for key, (count_col, mean_col) in columns.items()
        }

    result = {}
    for code in sorted(current_codes):
        areas = grouped.get(code, {})
        whole = next((area for raw, area in areas.items() if raw[-1] in "123"), None)
        if whole is not None:
            result[code] = {key: _mean([whole[key]]) for key in columns}
        else:
            result[code] = {key: _mean([area[key] for area in areas.values()]) for key in columns}
    return result, unmatched, recoded


def _mean(parts):
    candidates = [(count, mean) for count, mean in parts if count]
    if not candidates or any(mean is None for _, mean in candidates):
        return None
    return round(sum(count * mean for count, mean in candidates) / sum(count for count, _ in candidates), 2)


def parse_matura(rows, current_codes):
    """Read the whole-exam pass rate for each school powiat, excluding separate OKE rows."""
    _, groups, headings, *data = rows
    headings = [slug(value or "") for value in headings]
    code_col = headings.index("kod_teryt_powiatu")
    name_col = headings.index("powiat_nazwa")
    group_col = [slug(value or "") for value in groups].index("dla_calego_egzaminu_dojrzalosci")
    rate_col = headings.index("zdawalnosc", group_col)
    result = {code: {"matura_pass_pct": None} for code in sorted(current_codes)}
    unmatched = set()
    seen = set()
    for row in data:
        raw = str(row[code_col] or "").strip()
        if not raw.isascii() or not raw.isdigit():
            continue
        if slug(row[name_col] or "").startswith("okregowa_komisja_egzaminacyjna"):
            continue
        code = raw.zfill(4)
        if code not in result:
            unmatched.add(code)
            continue
        if code in seen:
            raise ValueError(f"Duplicate matura powiat {code}")
        seen.add(code)
        rate = _percentage(row[rate_col])
        result[code]["matura_pass_pct"] = round(rate, 2) if rate is not None else None
    return result, unmatched, current_codes - seen


class PlMoreExams(Source):
    info = SourceInfo(
        id="pl_more_exams",
        title="Eighth-grade exam and matura results",
        publisher="Central Examination Commission (CKE) and Centre for Education Informatics (CIE)",
        homepage=HOMEPAGE,
        license="Published public sector information; no separate file licence stated",
        description="September 2026 national exam workbooks. Results follow the location of the school.",
        used_for=["Eighth-grade subject means by gmina", "Matura pass rates by powiat"],
    )

    def fetch(self, force=False):
        for name, url in FILES.items():
            self.download(url, name, force=force, expect_binary=True)
        self.download(AREA_URL, AREA_FILE, force=force, expect_binary=True)

    def process(self):
        gminas = set(_area(self.raw_dir / AREA_FILE))
        powiaty = {code[:4] for code in gminas}
        e8, unmatched_e8, recoded = parse_e8(
            read_xlsx(self.raw_dir / E8_FILE, "SAS"), gminas
        )
        matura, unmatched_matura, missing_matura = parse_matura(
            read_xlsx(self.raw_dir / MATURA_FILE, "SAS"), powiaty
        )
        e8_note = "Main session, standard papers, by school location. Includes laureates and finalists."
        matura_note = "Formula 2023, September 2026 release, by school location. Whole-exam pass rate."
        notes = [
            "E8 standard papers exclude Ukrainian citizens who came to Poland after 24 February 2022.",
            "E8 town and rural parts of a gmina are combined using the number of candidates in each subject.",
            "E8 means suppressed for fewer than five candidates stay null, including combined gminas if a "
            "part with candidates has a suppressed mean.",
            "Matura rates come from the whole-exam column for candidates who sat all required exams. "
            "Separate examination commission rows do not contribute to the host powiat.",
        ]
        if unmatched_e8:
            notes.append("Unmatched E8 area codes: " + ", ".join(sorted(unmatched_e8)))
        if unmatched_matura:
            notes.append("Unmatched matura powiat codes: " + ", ".join(sorted(unmatched_matura)))
        if missing_matura:
            notes.append("Powiat codes without a matura row: " + ", ".join(sorted(missing_matura)))
        notes.extend(f"E8 TERYT code change: {old} to {new}." for old, new in sorted(recoded))
        return {
            "vintage": "September 2026",
            "_files": [*FILES, AREA_FILE],
            "tables": {
                "exam_e8": {
                    "level": "gmina",
                    "fields": {
                        key: {"label": label, "unit": "%", "year": 2026, "note": e8_note}
                        for key, label in (
                            ("e8_polish_mean_pct", "Eighth-grade Polish mean"),
                            ("e8_math_mean_pct", "Eighth-grade maths mean"),
                            ("e8_english_mean_pct", "Eighth-grade English mean"),
                        )
                    },
                    "rows": e8,
                },
                "exam_matura": {
                    "level": "powiat",
                    "fields": {
                        "matura_pass_pct": {
                            "label": "Matura pass rate", "unit": "%", "year": 2026, "note": matura_note,
                        },
                    },
                    "rows": matura,
                },
            },
            "notes": notes,
        }

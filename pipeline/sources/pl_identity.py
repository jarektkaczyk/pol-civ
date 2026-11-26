"""National and ethnic identity and home language by gmina: NSP 2021 census final results (GUS).

* "Przynaleznosc narodowo-etniczna - dane NSP 2021 dla kraju i jednostek podzialu terytorialnego"
  (xlsx, added 20 Dec 2023), TABL. 5: residents of each gmina by national or ethnic identification,
  first or second declaration (a person may give two, so identities do not add up to the total).
* "Jezyk uzywany w domu - dane NSP 2021 ..." (xlsx, same date), TABL. 5: residents by language used
  at home (a person may give more than one).

GUS lists an identity or a language in a gmina only when at least 10 people declared it. A missing
row is therefore "fewer than 10 people", which this source keeps as null (never 0). Census date:
31 March 2021. Gmina codes are TERYT 7-digit codes of 2021.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.source import Source, SourceInfo
from ._pl_xlsx import read_xlsx
from .pl_soc_common import slug

BASE = "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/6536/10/1/1/"
IDENTITY_URL = BASE + "przynaleznosc_narodowo-etniczna_-_dane_nsp_2021_dla_kraju_i_jednostek_podzialu_terytorialnego_v2.xlsx"
LANGUAGE_URL = BASE + "jezyk_uzywany_w_domu_-_dane_nsp_2021_dla_kraju_i_jednostek_podzialu_terytorialnego.xlsx"
IDENTITY_FILE = "nsp2021_identity.xlsx"
LANGUAGE_FILE = "nsp2021_language.xlsx"
PAGE = ("https://stat.gov.pl/spisy-powszechne/nsp-2021/nsp-2021-wyniki-ostateczne/tablice-z-ostatecznymi-danymi-w-"
        "zakresie-przynaleznosci-narodowo-etnicznej-jezyka-uzywanego-w-domu-oraz-przynaleznosci-do-wyznania-"
        "religijnego,10,1.html")

# Census label (ASCII slug) -> field key, English label. Names follow the census list.
IDENTITIES = {
    "slaska": ("silesian", "Silesian"),
    "kaszubska": ("kashubian", "Kashubian"),
    "niemiecka": ("german", "German"),
    "ukrainska": ("ukrainian", "Ukrainian"),
    "bialoruska": ("belarusian", "Belarusian"),
    "lemkowska": ("lemko", "Lemko"),
    "romska": ("roma", "Roma"),
    "litewska": ("lithuanian", "Lithuanian"),
    "rosyjska": ("russian", "Russian"),
    "zydowska": ("jewish", "Jewish"),
    "ormianska": ("armenian", "Armenian"),
    "czeska": ("czech", "Czech"),
    "slowacka": ("slovak", "Slovak"),
    "tatarska": ("tatar", "Tatar"),
    "karaimska": ("karaim", "Karaim"),
}
LANGUAGES = {
    "slaski": ("lang_silesian", "Silesian"),
    "kaszubski": ("lang_kashubian", "Kashubian"),
    "niemiecki": ("lang_german", "German"),
    "lemkowski": ("lang_lemko", "Lemko"),
    "bialoruski": ("lang_belarusian", "Belarusian"),
    "ukrainski": ("lang_ukrainian", "Ukrainian"),
}
# Labels that are not one identity: the total, the Polish identity, the non-Polish subtotal, the undetermined
# and the "only supranational" answers. Every other label is one census identity.
NOT_ONE_IDENTITY = ("ogolem", "polska", "inna_niz_polska", "nieustalona", "wylacznie_ponadnarodowa", "slasko_")
THRESHOLD_NOTE = "31 March 2021 (NSP 2021). Blank where fewer than 10 people in the gmina declared it."


def _label(value) -> str:
    """ASCII key of a census label ('Inna niz polska\n w tym:' -> 'inna_niz_polska')."""
    key = slug(str(value or ""))
    return key[: -len("_w_tym")] if key.endswith("_w_tym") else key


def parse_gmina_table(rows: list[list]) -> dict[str, dict[str, int]]:
    """{TERYT7: {ASCII slug of the census label: persons}} from a GUS NSP 2021 TABL. 5 (gmina) sheet.

    The sheet has one row per gmina and label: [_, voivodeship, powiat, gmina, code, label, persons, percent].
    """
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        if len(r) < 7:
            continue
        code, label, value = r[4], r[5], r[6]
        if not (isinstance(code, str) and re.fullmatch(r"\d{7}", code)):
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        lab = _label(label)
        out.setdefault(code, {})[lab] = int(value)
    return out


def identity_record(labels: dict[str, int]) -> dict:
    """Counts and shares (percent of all residents) of the named identities, plus the largest non-Polish one."""
    total = labels.get("ogolem")
    rec: dict = {"total": total, "polish": labels.get("polska"), "non_polish": labels.get("inna_niz_polska")}
    for lab, (key, _name) in IDENTITIES.items():
        n = labels.get(lab)
        rec[key] = n
        rec[f"{key}_share"] = round(n / total * 100, 3) if n is not None and total else None
    # Largest single identity other than Polish, among every census identity (not only the named ones).
    best = None
    for lab, n in labels.items():
        if lab.startswith(NOT_ONE_IDENTITY):
            continue
        if best is None or n > best[1] or (n == best[1] and lab < best[0]):
            best = (lab, n)
    if best:
        key = IDENTITIES.get(best[0], (None, None))[0]
        rec["largest_minority"] = key or "other"
        rec["largest_minority_label"] = best[0]
        rec["largest_minority_count"] = best[1]
        rec["largest_minority_share"] = round(best[1] / total * 100, 3) if total else None
    else:
        rec["largest_minority"] = None
        rec["largest_minority_label"] = None
        rec["largest_minority_count"] = None
        rec["largest_minority_share"] = None
    return rec


def language_record(labels: dict[str, int]) -> dict:
    total = labels.get("ogolem")
    rec: dict = {"total": total}
    for lab, (key, _name) in LANGUAGES.items():
        n = labels.get(lab)
        rec[key] = n
        rec[f"{key}_share"] = round(n / total * 100, 3) if n is not None and total else None
    return rec


def _field(label: str, unit: str, note: str = THRESHOLD_NOTE) -> dict:
    return {"label": label, "unit": unit, "year": 2021, "note": note}


class PolandIdentity(Source):
    info = SourceInfo(
        id="pl_identity",
        title="National and ethnic identity and home language, NSP 2021",
        publisher="Statistics Poland (GUS)",
        homepage=PAGE,
        license="GUS CC BY 4.0",
        description="Residents of each gmina by national or ethnic identification (first or second declaration) "
                    "and by language used at home, census of 31 March 2021.",
        used_for=["Identity lenses (Silesian, Kashubian, German, Belarusian, largest minority identity)"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(IDENTITY_URL, IDENTITY_FILE, force=force, expect_binary=True)
        self.download(LANGUAGE_URL, LANGUAGE_FILE, force=force, expect_binary=True)

    def process(self) -> dict:
        ident = parse_gmina_table(read_xlsx(Path(self.raw_dir / IDENTITY_FILE), "TABL. 5"))
        lang = parse_gmina_table(read_xlsx(Path(self.raw_dir / LANGUAGE_FILE), "TABL. 5"))
        if len(ident) < 2400 or len(lang) < 2400:
            raise RuntimeError(f"expected about 2,477 gminas, got {len(ident)} (identity), {len(lang)} (language)")
        id_rows = {code: identity_record(labels) for code, labels in sorted(ident.items())}
        lang_rows = {code: language_record(labels) for code, labels in sorted(lang.items())}
        id_fields = {
            "total": _field("Residents", "persons", "31 March 2021 (NSP 2021)."),
            "polish": _field("Polish identity", "persons"),
            "non_polish": _field("An identity other than Polish", "persons"),
        }
        for _lab, (key, name) in IDENTITIES.items():
            id_fields[key] = _field(f"{name} identity", "persons")
            id_fields[f"{key}_share"] = _field(f"{name} identity", "% of residents")
        id_fields["largest_minority"] = _field(
            "Largest identity other than Polish", "category",
            "31 March 2021 (NSP 2021). Key of the named identity with the most people, or 'other'; blank where "
            "no identity other than Polish reached 10 people.")
        id_fields["largest_minority_label"] = _field("Largest identity other than Polish (census label)", "text")
        id_fields["largest_minority_count"] = _field("People with the largest identity other than Polish", "persons")
        id_fields["largest_minority_share"] = _field("Largest identity other than Polish", "% of residents")
        lang_fields = {"total": _field("Residents", "persons", "31 March 2021 (NSP 2021).")}
        for _lab, (key, name) in LANGUAGES.items():
            lang_fields[key] = _field(f"{name} used at home", "persons")
            lang_fields[f"{key}_share"] = _field(f"{name} used at home", "% of residents")
        return {
            "vintage": "NSP 2021 (31 March 2021), final results of 20 December 2023",
            "tables": {
                "identity_gmina": {"level": "gmina", "fields": id_fields, "rows": id_rows},
                "language_gmina": {"level": "gmina", "fields": lang_fields, "rows": lang_rows},
            },
            "notes": [
                "A person could declare two national or ethnic identities (first and second): the counts are of "
                "people who gave the identity in either declaration, so they do not add up to the total.",
                "GUS lists an identity or language in a gmina only when at least 10 people declared it; "
                "fewer than 10 stays null.",
                "Identity names follow the census list; 'slasko-cieszynska' is a separate census answer and is "
                "not counted as Silesian.",
                "Gmina codes are those of 2021; builders match them on the first six digits.",
                "Silesian (slaski) home language does not include the separate answer 'gwara slaska'.",
            ],
            "_files": [IDENTITY_FILE, LANGUAGE_FILE],
        }

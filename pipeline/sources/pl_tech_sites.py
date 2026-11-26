"""Tech and games in Poland: video game studios from Wikidata, plus a curated list of tech landmarks.

Game studios (Wikidata, CC0): every item that is a video game developer or publisher (or in the video game industry),
in Poland or with its headquarters (P159) in Poland, not dissolved (no P576), whose headquarters has coordinates in
Poland, and that developed (P178) at least one game released by 2026. Its best-known game is the one with the most
Wikipedia sitelinks (released by 2026); the picks of the largest studios were checked by hand and a few are set in
pl_tech_sites.json `studio_games`. Positions are the headquarters town, so the map groups studios by town. Wikidata
headquarters can be stale: `studio_place` moves a studio to the town its register entry or an independent page gives
(with that page as `ref`), and `studio_drop` removes studios known to have closed without a Wikidata dissolution date
(Wikidata game lists are too incomplete to judge activity from the newest game).

Tech landmarks (pl_tech_sites.json): scale-ups at their main Polish office (marked `office` when the legal seat is
abroad), the Polish systems on the TOP500 list of November 2026 (one point per computing centre), satellite and
space-instrument makers, the 2025 patent leader and the first cloud regions. Each has a one-line fact, the year of
the fact and the `ref` page it was read from; fetch() caches those pages so the Almanac lists them.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse

from ..core.source import Source, SourceInfo
from ._econ_sites import LAT, LON, cache_refs, cached_refs, check_item, load_json, to_point

CURATED = "pl_tech_sites.json"
SPARQL_URL = "https://query.wikidata.org/sparql?"
LAST_YEAR = 2026  # games released after this year are announcements, not a studio's best-known game

STUDIOS_Q = """SELECT ?studio ?studioLabel ?hq ?hqLabel ?coord ?inception ?dissolved
       (COUNT(DISTINCT ?game) AS ?games) (COUNT(DISTINCT ?sitelink) AS ?sitelinks) WHERE {
  { ?studio wdt:P31/wdt:P279* wd:Q210167 } UNION { ?studio wdt:P31/wdt:P279* wd:Q1137109 } UNION { ?studio wdt:P452 wd:Q941594 }
  { ?studio wdt:P17 wd:Q36 } UNION { ?studio wdt:P159/wdt:P17 wd:Q36 }
  OPTIONAL { ?studio wdt:P159 ?hq . OPTIONAL { ?hq wdt:P625 ?coord } }
  OPTIONAL { ?studio wdt:P571 ?inception }
  OPTIONAL { ?studio wdt:P576 ?dissolved }
  OPTIONAL { ?game wdt:P178 ?studio }
  OPTIONAL { ?sitelink schema:about ?studio }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "pl,en,mul". }
} GROUP BY ?studio ?studioLabel ?hq ?hqLabel ?coord ?inception ?dissolved"""

GAMES_Q = """SELECT ?studio ?game ?gameLabel ?year ?links WHERE {
  VALUES ?studio { %s }
  ?game wdt:P178 ?studio ; wikibase:sitelinks ?links .
  OPTIONAL { ?game wdt:P577 ?date . BIND(YEAR(?date) AS ?year) }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,pl,mul". }
}"""

ACCEPT = {"Accept": "application/sparql-results+json"}


def sparql_url(query: str) -> str:
    return SPARQL_URL + urllib.parse.urlencode({"query": query, "format": "json"})


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def parse_point(wkt: str | None) -> tuple[float, float] | None:
    if not wkt or not wkt.startswith("Point("):
        return None
    lon, lat = wkt[6:-1].split()
    return float(lon), float(lat)


def in_poland(lon: float, lat: float) -> bool:
    return LON[0] < lon < LON[1] and LAT[0] < lat < LAT[1]


def _val(b: dict, key: str):
    return (b.get(key) or {}).get("value")


def studio_rows(bindings: list[dict], hq_pick: dict[str, str] | None = None) -> dict[str, dict]:
    """QID -> {name, hq, hq_name, lon, lat, sitelinks} for active studios whose headquarters is a place in Poland.

    A studio with several headquarters takes the one named in `hq_pick` (studio QID -> HQ QID), else the first by
    town name. Headquarters "Poland" (Q36) or outside Poland are not places on the map.
    """
    hq_pick = hq_pick or {}
    cand: dict[str, list[dict]] = {}
    for b in bindings:
        q = qid(_val(b, "studio"))
        if _val(b, "dissolved"):
            cand.setdefault(q, []).append({"dissolved": True})
            continue
        hq = _val(b, "hq")
        pt = parse_point(_val(b, "coord"))
        if not hq or qid(hq) == "Q36" or pt is None or not in_poland(*pt):
            continue
        cand.setdefault(q, []).append({
            "name": _val(b, "studioLabel"), "hq": qid(hq), "hq_name": _val(b, "hqLabel"),
            "lon": round(pt[0], 5), "lat": round(pt[1], 5), "sitelinks": int(_val(b, "sitelinks") or 0),
        })
    out = {}
    for q, rows in cand.items():
        if any(r.get("dissolved") for r in rows):
            continue
        if not rows:
            continue
        pick = hq_pick.get(q)
        chosen = next((r for r in rows if r["hq"] == pick), None)
        if chosen is None:
            chosen = sorted(rows, key=lambda r: (r["hq_name"] or "", r["hq"]))[0]
        out[q] = chosen
    return out


def best_games(bindings: list[dict], last_year: int = LAST_YEAR) -> dict[str, list[dict]]:
    """Studio QID -> its games released by `last_year` (or undated), most sitelinks first, then newest."""
    games: dict[str, dict[str, dict]] = {}
    for b in bindings:
        year = _val(b, "year")
        year = int(year) if year else None
        if year is not None and year > last_year:
            continue
        s, g = qid(_val(b, "studio")), qid(_val(b, "game"))
        title = _val(b, "gameLabel")
        if not title or title == g:
            continue  # no label in en/pl: not a title the page can show
        cur = games.setdefault(s, {}).get(g)
        if cur is None or (year or 0) < (cur["year"] or 9999):
            games[s][g] = {"qid": g, "title": title, "year": year, "links": int(_val(b, "links") or 0)}
    return {s: sorted(d.values(), key=lambda x: (-x["links"], -(x["year"] or 0), x["title"])) for s, d in games.items()}


class PlTechSites(Source):
    info = SourceInfo(
        id="pl_tech_sites",
        title="Tech and games: game studios and tech landmarks",
        publisher="Wikidata (game studios); company, TOP500, Polish Patent Office and press pages (landmarks)",
        homepage="https://www.wikidata.org/",
        license="Wikidata: CC0; landmark facts: short quotations of figures with the page named",
        description="Polish video game studios with their headquarters town and best-known game (Wikidata), and a "
        "curated list of tech landmarks: scale-ups at their main Polish office, the Polish TOP500 supercomputers "
        "(November 2026 list), satellite makers, the 2025 patent leader and the first cloud regions, each with one "
        "fact, its year and the page it comes from.",
        used_for=["Tech and games map layer", "City View"],
    )

    def _studios(self) -> list[dict]:
        return json.loads((self.raw_dir / "wikidata_studios.json").read_text(encoding="utf-8"))["results"]["bindings"]

    def _query(self, query: str, rel: str, force: bool, attempts: int = 10) -> None:
        """One SPARQL query, cached; on HTTP 429 waits the server's limit (about a minute) and tries again."""
        if (self.raw_dir / rel).exists() and not force or self.offline:
            self.download(sparql_url(query), rel)
            return
        for n in range(attempts):
            try:
                self.download(sparql_url(query), rel, force=force, headers=ACCEPT)
                return
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or n == attempts - 1:
                    raise
                exc.close()
                print("      Wikidata rate limit; waiting 90 s")
                time.sleep(90)

    def fetch(self, force=False):
        cur = load_json(__file__, CURATED)
        self._query(STUDIOS_Q, "wikidata_studios.json", force)
        qids = sorted(studio_rows(self._studios(), cur.get("studio_hq")))
        values = " ".join(f"wd:{q}" for q in qids)
        self._query(GAMES_Q % values, "wikidata_games.json", force)
        for note in cache_refs(self, cur["items"], force=force):
            print(f"      ! {note}")

    def process(self):
        cur = load_json(__file__, CURATED)
        kinds = {k["id"] for k in cur["kinds"]}
        problems = [p for it in cur["items"] for p in check_item(it, kinds)]
        if problems:
            raise ValueError("pl_tech_sites.json: " + "; ".join(problems))
        studios = studio_rows(self._studios(), cur.get("studio_hq"))
        games_doc = json.loads((self.raw_dir / "wikidata_games.json").read_text(encoding="utf-8"))
        games = best_games(games_doc["results"]["bindings"])
        picks = cur.get("studio_games") or {}
        drop = set(cur.get("studio_drop") or {})
        for q, fix in (cur.get("studio_place") or {}).items():
            if q in studios:
                studios[q] = {**studios[q], **{k: fix[k] for k in ("hq", "hq_name", "lon", "lat")}, "ref": fix["ref"]}
        points = []
        for q, s in sorted(studios.items(), key=lambda kv: (-kv[1]["sitelinks"], kv[1]["name"] or "")):
            if q in drop or not games.get(q):
                continue
            listed = games[q]
            best = listed[0]
            pick = picks.get(q)
            if pick:
                best = next((g for g in listed if g["qid"] == pick["game"]), None)
                if best is None:
                    raise ValueError(f"studio_games: {q} has no game {pick['game']} in the Wikidata result")
            points.append({
                "id": f"studio_{q}", "name": s["name"], "kind": "studio", "lon": s["lon"], "lat": s["lat"],
                "props": {"place": s["hq_name"], "qid": q, "hq": s["hq"], "game": best["title"],
                          "game_qid": best["qid"], "year": best["year"], "games": len(listed),
                          "sitelinks": s["sitelinks"], "hand_checked": bool(pick),
                          "ref": f"https://www.wikidata.org/wiki/{q}",
                          **({"place_ref": s["ref"]} if s.get("ref") else {})},
            })
        landmarks = [to_point(it, ("seat_note",)) for it in cur["items"]]
        files, ref_notes = cached_refs(self, cur["items"])
        return {
            "vintage": "Wikidata game studios; landmarks curated November 2026",
            "points": landmarks + points,
            "notes": ["rule: " + cur["rule"], "rule (studios): " + cur["studio_rule"]] + ref_notes,
            "_files": ["wikidata_studios.json", "wikidata_games.json"] + files,
        }

"""Natural Earth 1:10m around Poland: neighbouring countries, named lakes and lagoons, and river names."""

from ..core.geo import PL_LAT, PL_LON, bbox_intersects, geojson_lines, geojson_rings, load_geojson
from ..core.source import Source, SourceInfo

TAG = "v5.1.2"  # pinned release, so the content (and sha256) cannot change under the same URL
BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{TAG}/geojson"
PAD = 1.5  # degrees around the map window, so outlines that cross its edge are kept whole
BBOX = (PL_LON[0] - PAD, PL_LAT[0] - PAD, PL_LON[1] + PAD, PL_LAT[1] + PAD)
FILES = ["ne_10m_admin_0_countries", "ne_10m_lakes", "ne_10m_lakes_europe",
         "ne_10m_rivers_lake_centerlines", "ne_10m_rivers_europe"]


# Natural Earth's 1:10m river file has English names only; these Polish rivers get their Polish name (the
# Europe supplement's name_pl supplies the others, e.g. Oder -> Odra).
POLISH_NAMES = {"Vistula": "Wisła"}


def _name(p: dict, aliases: dict | None = None) -> str | None:
    if p.get("name_pl"):
        return p["name_pl"]
    name = p.get("name") or None
    return (aliases or {}).get(name, POLISH_NAMES.get(name, name))


class PlGeoNe(Source):
    info = SourceInfo(
        id="pl_geo_ne",
        title="Natural Earth 1:10m (countries, lakes, rivers, Europe supplements)",
        publisher="Natural Earth",
        homepage="https://www.naturalearthdata.com/",
        license="Public domain",
        description="Outlines of the neighbouring countries (Germany, Czechia, Slovakia, Ukraine, Belarus, Lithuania, "
        "Russia's Kaliningrad oblast; shown under fog), the Vistula Lagoon, and the names of the larger lakes "
        f"and rivers. Files are pinned to the natural-earth-vector release {TAG}.",
        used_for=["Neighbouring countries", "Lagoons", "Lake and river names"],
    )

    def _path(self, name):
        return f"{TAG}/{name}.geojson"

    def fetch(self, force=False):
        for name in FILES:
            self.download(f"{BASE}/{name}.geojson", self._path(name), force=force)

    def _features(self, name):
        return load_geojson(self.raw_dir / self._path(name))

    def process(self):
        countries = []
        for f in self._features("ne_10m_admin_0_countries"):
            p = f["properties"]
            rings = [r for r in geojson_rings(f["geometry"]) if bbox_intersects(r, BBOX)]
            if rings:
                countries.append({"iso": p.get("ADM0_A3"), "name": p.get("ADMIN"), "rings": rings})
        lakes = []
        for name in ("ne_10m_lakes", "ne_10m_lakes_europe"):
            for f in self._features(name):
                if not f.get("geometry"):
                    continue
                rings = geojson_rings(f["geometry"])
                if rings and bbox_intersects(rings[0], BBOX):
                    p = f["properties"]
                    lakes.append({"name": _name(p), "name_en": p.get("name"), "featurecla": p.get("featurecla"),
                                  "rings": rings})
        aliases = {f["properties"]["name"]: f["properties"]["name_pl"]
                   for f in self._features("ne_10m_rivers_europe")
                   if f["properties"].get("name") and f["properties"].get("name_pl")}
        rivers = []
        for name in ("ne_10m_rivers_lake_centerlines", "ne_10m_rivers_europe"):
            for f in self._features(name):
                if not f.get("geometry"):
                    continue
                p = f["properties"]
                for line in geojson_lines(f["geometry"]):
                    if bbox_intersects(line, BBOX):
                        rivers.append({"name": _name(p, aliases), "name_en": p.get("name"), "rank": p.get("scalerank"),
                                       "featurecla": p.get("featurecla"), "line": line})
        print(f"    {len(countries)} countries, {len(lakes)} lakes, {len(rivers)} river lines in the window")
        return {
            "vintage": f"Natural Earth {TAG} (1:10m)",
            "_files": [self._path(n) for n in FILES],
            "countries": countries,
            "lakes": lakes,
            "rivers": rivers,
        }

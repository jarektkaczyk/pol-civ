"""Parsing and geometry helpers of the pol-civ geography sources and the world builder."""

import math
import struct
import unittest
import zlib
from collections import Counter

from pipeline.build import states as states_mod
from pipeline.build import world
from pipeline.core.geo import Albers, Shape, read_dbf, read_shp, topojson_arcs, topojson_rings
from pipeline.core.hexgrid import HexGrid
from pipeline.sources import _pl_geo_raster as rast
from pipeline.sources.pl_geo_lau import teryt6_of_lau
from pipeline.sources.pl_geo_teryt import clean_name, teryt_of, voivodeship_name


def lzw_encode(data: bytes) -> bytes:
    """TIFF LZW encoder (MSB-first, early change), only for the tests."""
    out, bitbuf, nbits = bytearray(), 0, 0
    width = 9

    def emit(code):
        nonlocal bitbuf, nbits
        bitbuf = (bitbuf << width) | code
        nbits += width
        while nbits >= 8:
            nbits -= 8
            out.append((bitbuf >> nbits) & 0xFF)

    table = {bytes([k]): k for k in range(256)}
    nxt = 258
    emit(256)
    w = b""
    for b in data:
        wc = w + bytes([b])
        if wc in table:
            w = wc
            continue
        emit(table[w])
        table[wc] = nxt
        nxt += 1
        if nxt >= (1 << width) and width < 12:
            width += 1
        w = bytes([b])
    if w:
        emit(table[w])
    emit(257)
    if nbits:
        out.append((bitbuf << (8 - nbits)) & 0xFF)
    return bytes(out)


def tiny_tiff(tiles: list[bytes], width: int, height: int, tw: int, th: int, compression: int, bigtiff=False) -> bytes:
    """A little-endian tiled 8-bit TIFF with the given (already compressed) tiles."""
    entries_n = 8
    if bigtiff:
        head = b"II" + struct.pack("<HHHQ", 43, 8, 0, 16)
        ifd_size = 8 + entries_n * 20 + 8
    else:
        head = b"II" + struct.pack("<HI", 42, 8)
        ifd_size = 2 + entries_n * 12 + 4
    data_start = len(head) + ifd_size + 2 * 8 * len(tiles)
    offsets, counts, blob = [], [], b""
    for t in tiles:
        offsets.append(data_start + len(blob))
        counts.append(len(t))
        blob += t
    arr_off = len(head) + ifd_size
    off_arr = struct.pack(f"<{len(tiles)}Q", *offsets) if bigtiff else struct.pack(f"<{len(tiles)}I", *offsets)
    cnt_arr = struct.pack(f"<{len(tiles)}Q", *counts) if bigtiff else struct.pack(f"<{len(tiles)}I", *counts)
    arrays = off_arr + cnt_arr
    arrays += bytes(2 * 8 * len(tiles) - len(arrays))
    ent = []

    def e(tag, ftype, count, value_bytes):
        ent.append((tag, ftype, count, value_bytes))

    if bigtiff:
        e(256, 4, 1, struct.pack("<I", width) + bytes(4))
        e(257, 4, 1, struct.pack("<I", height) + bytes(4))
        e(258, 3, 1, struct.pack("<H", 8) + bytes(6))
        e(259, 3, 1, struct.pack("<H", compression) + bytes(6))
        e(322, 3, 1, struct.pack("<H", tw) + bytes(6))
        e(323, 3, 1, struct.pack("<H", th) + bytes(6))
        e(324, 16, len(tiles), struct.pack("<Q", arr_off))
        e(325, 16, len(tiles), struct.pack("<Q", arr_off + len(off_arr)))
        ifd = struct.pack("<Q", len(ent)) + b"".join(struct.pack("<HHQ", t, f, c) + v for t, f, c, v in ent) + bytes(8)
    else:
        e(256, 4, 1, struct.pack("<I", width))
        e(257, 4, 1, struct.pack("<I", height))
        e(258, 3, 1, struct.pack("<H", 8) + bytes(2))
        e(259, 3, 1, struct.pack("<H", compression) + bytes(2))
        e(322, 3, 1, struct.pack("<H", tw) + bytes(2))
        e(323, 3, 1, struct.pack("<H", th) + bytes(2))
        cnt_tiles = len(tiles)
        e(324, 4, cnt_tiles, struct.pack("<I", arr_off) if cnt_tiles > 1 else struct.pack("<I", offsets[0]))
        e(325, 4, cnt_tiles, struct.pack("<I", arr_off + len(off_arr)) if cnt_tiles > 1 else struct.pack("<I", counts[0]))
        ifd = struct.pack("<H", len(ent)) + b"".join(struct.pack("<HHI", t, f, c) + v for t, f, c, v in ent) + bytes(4)
    return head + ifd + arrays + blob


class RasterTest(unittest.TestCase):
    def test_lzw_roundtrip(self):
        for data in (b"", b"A", b"TOBEORNOTTOBEORTOBEORNOT" * 20, bytes(range(256)) * 30, bytes([7]) * 5000):
            self.assertEqual(rast.lzw_decode(lzw_encode(data)), data)

    def test_real_lzw_tiff(self):
        """A 300 x 200 grey TIFF written by the macOS image tools (LZW + horizontal predictor, one strip)."""
        from pathlib import Path

        b = (Path(__file__).parent / "fixtures" / "lzw_predictor.tif").read_bytes()
        endian, big, first = rast.tiff_header(b[:16])
        ifd = rast.read_ifds(b, 0, endian, big, first)[0]
        self.assertEqual((ifd[259][0], ifd[317][0]), (5, 2))
        data = b"".join(rast.lzw_decode(b[o:o + n]) for o, n in zip(ifd[273], ifd[279]))
        data = rast.undo_horizontal_predictor(data, 300)
        want = bytes(((x * 7 + y * 13) % 251 if (x // 20 + y // 20) % 2 else x % 5) for y in range(200) for x in range(300))
        self.assertEqual(data, want)

    def test_predictor(self):
        self.assertEqual(rast.undo_horizontal_predictor(bytes([10, 1, 1, 5, 255, 1]), 3), bytes([10, 11, 12, 5, 4, 5]))

    def test_decode_tile_deflate_and_padding(self):
        px = bytes(range(12))
        self.assertEqual(rast.decode_tile(zlib.compress(px), 8, 1, 4, 3), px)
        self.assertEqual(rast.decode_tile(zlib.compress(px[:8]), 8, 1, 4, 3), px[:8] + bytes(4))
        with self.assertRaises(ValueError):
            rast.decode_tile(px, 7, 1, 4, 3)

    def _roundtrip(self, bigtiff, compression):
        tw = th = 4
        tiles_px = [bytes([10 * k + j for j in range(16)]) for k in range(4)]
        enc = (lambda b: zlib.compress(b)) if compression == 8 else lzw_encode
        tif = tiny_tiff([enc(t) for t in tiles_px], 8, 8, tw, th, compression, bigtiff)
        endian, big, first = rast.tiff_header(tif[:16])
        self.assertEqual(big, bigtiff)
        ifd = rast.read_ifds(tif, 0, endian, big, first)[0]
        self.assertEqual(rast.ifd_int(ifd, rast.TAG_WIDTH), 8)
        offs, counts = ifd[rast.TAG_TILE_OFFSETS], ifd[rast.TAG_TILE_COUNTS]
        got = [rast.decode_tile(tif[o:o + n], compression, 1, tw, th) for o, n in zip(offs, counts)]
        self.assertEqual(got, tiles_px)

    def test_tiff_and_bigtiff(self):
        for big in (False, True):
            for comp in (8, 5):
                self._roundtrip(big, comp)

    def test_pointer_outside_buffer(self):
        tif = tiny_tiff([zlib.compress(bytes(16))] * 4, 8, 8, 4, 4, 8, bigtiff=True)
        endian, big, first = rast.tiff_header(tif[:16])
        ifd = rast.read_ifds(tif[:first + 200], 0, endian, big, first)[0]
        self.assertIsInstance(ifd[rast.TAG_TILE_OFFSETS], rast.Pointer)
        self.assertEqual(len(rast.read_values(tif, 0, ifd[rast.TAG_TILE_OFFSETS])), 4)

    def test_not_a_tiff(self):
        with self.assertRaises(ValueError):
            rast.tiff_header(b"GIF89a" + bytes(10))

    def test_esri_ascii(self):
        text = "ncols 3\nnrows 2\nxllcenter 20.0\nyllcenter 49.0\ncellsize 0.5\nnodata_value -9999\n1 2 3\n4 -9999 6\n"
        g = rast.parse_esri_ascii(text)
        self.assertEqual((g["ncols"], g["nrows"], g["xll"], g["yll"]), (3, 2, 20.0, 49.0))
        self.assertEqual(g["rows"], [[1.0, 2.0, 3.0], [4.0, None, 6.0]])
        corner = rast.parse_esri_ascii(text.replace("xllcenter 20.0", "xllcorner 19.75").replace("yllcenter", "yllcorner"))
        self.assertEqual(corner["xll"], 20.0)
        with self.assertRaises(ValueError):
            rast.parse_esri_ascii(text.replace("nrows 2", "nrows 3"))


class VectorFormatTest(unittest.TestCase):
    def test_topojson(self):
        topo = {"transform": {"scale": [0.5, 0.25], "translate": [10, 50]},
                "arcs": [[[0, 0], [2, 0], [0, 4]], [[2, 4], [-2, 0], [0, -4]]]}
        arcs = topojson_arcs(topo)
        self.assertEqual(arcs[0], [(10.0, 50.0), (11.0, 50.0), (11.0, 51.0)])
        ring = topojson_rings(arcs, {"type": "Polygon", "arcs": [[0, 1]]})[0]
        self.assertEqual(ring, [(10.0, 50.0), (11.0, 50.0), (11.0, 51.0), (10.0, 51.0), (10.0, 50.0)])
        rev = topojson_rings(arcs, {"type": "MultiPolygon", "arcs": [[[~1, ~0]]]})[0]
        self.assertEqual(rev[0], (10.0, 50.0))
        self.assertEqual(len(rev), 5)

    def test_dbf(self):
        fields = [(b"NAME", b"C", 8, 0), (b"UP", b"N", 6, 0), (b"DIS", b"N", 8, 2)]
        recs = [(b"Wis\xc5\x82a", b"194000", b"  1080.5"), (b"San", b"      ", b"   129.0")]
        hlen = 32 + 32 * len(fields) + 1
        rlen = 1 + sum(f[2] for f in fields)
        head = struct.pack("<BBBBIHH", 3, 126, 1, 1, len(recs), hlen, rlen) + bytes(20)
        fd = b"".join(n.ljust(11, b"\0") + t + bytes(4) + bytes([ln, dec]) + bytes(14) for n, t, ln, dec in fields)
        body = b"".join(b" " + a.ljust(8) + b.rjust(6) + c.rjust(8) for a, b, c in recs)
        rows = read_dbf(head + fd + b"\r" + body + b"\x1a")
        self.assertEqual(rows[0], {"NAME": "Wisła", "UP": 194000, "DIS": 1080.5})
        self.assertIsNone(rows[1]["UP"])

    def test_shp_polyline(self):
        pts = [(19.0, 50.0), (19.5, 50.5), (20.0, 50.2)]
        body = struct.pack("<i4d", 3, 19.0, 50.0, 20.0, 50.5) + struct.pack("<ii", 1, 3) + struct.pack("<i", 0)
        body += b"".join(struct.pack("<dd", *p) for p in pts)
        rec = struct.pack(">ii", 1, len(body) // 2) + body
        null = struct.pack(">ii", 2, 2) + struct.pack("<i", 0)
        shp = bytes(100) + rec + null
        out = list(read_shp(shp))
        self.assertEqual(out[0], (3, [pts]))
        self.assertEqual(out[1], (0, []))


class CodesTest(unittest.TestCase):
    def test_lau_to_teryt6(self):
        self.assertEqual(teryt6_of_lau("1001121216101"), "126101")  # Krakow
        self.assertEqual(teryt6_of_lau("1007141286501"), "146501")  # Warszawa
        self.assertEqual(teryt6_of_lau("1007142710307"), "140307")  # Maciejowice

    def test_bdl_to_teryt(self):
        self.assertEqual(teryt_of("011212001011", 6), "1201011")
        self.assertEqual(teryt_of("071427103073", 6), "1403073")
        self.assertEqual(teryt_of("071427164000", 5), "1464")
        self.assertEqual(teryt_of("011200000000", 2), "12")

    def test_names(self):
        self.assertEqual(voivodeship_name("KUJAWSKO-POMORSKIE"), "Kujawsko-Pomorskie")
        self.assertEqual(voivodeship_name("ŚLĄSKIE"), "Śląskie")
        self.assertEqual(clean_name("Wałbrzych od 2013"), "Wałbrzych")
        self.assertEqual(clean_name("M.st.Warszawa od 2002"), "Warszawa")


class WorldHelpersTest(unittest.TestCase):
    def test_albers_centre(self):
        x, y = Albers()(19.3, 52.0)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        lon, lat = Albers().inverse(*Albers()(23.5, 49.2))
        self.assertAlmostEqual(lon, 23.5, places=6)
        self.assertAlmostEqual(lat, 49.2, places=6)

    def test_inscribed_window_is_inside(self):
        a = Albers()
        x0, y0, x1, y1 = world.inscribed_window(a)
        for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
            lon, lat = a.inverse(x, y)
            self.assertTrue(13.6 - 1e-6 <= lon <= 24.6 + 1e-6 and 48.75 - 1e-6 <= lat <= 55.15 + 1e-6, (lon, lat))
        self.assertGreater(x1 - x0, 650)
        self.assertGreater(y1 - y0, 650)

    def test_relief(self):
        self.assertEqual(world.classify_relief(120, 10, 140), world.FLAT)
        self.assertEqual(world.classify_relief(200, 40, 320), world.HILLS)
        self.assertEqual(world.classify_relief(700, 150, 1100), world.MOUNTAINS)
        self.assertEqual(world.classify_relief(800, 120, 1300), world.MOUNTAINS)
        self.assertEqual(world.classify_relief(1500, 380, 2450), world.PEAKS)  # the Tatra
        self.assertEqual(world.classify_relief(900, 200, 1600), world.PEAKS)  # the Karkonosze

    def test_cover(self):
        ft = Counter({"n": 30, "d": 5})
        self.assertEqual(world.dominant_cover(Counter({10: 60, 40: 40}), 100, 150, ft), 2)  # pines
        self.assertEqual(world.dominant_cover(Counter({10: 60, 40: 40}), 100, 150, Counter({"d": 9, "m": 3})), 1)
        self.assertEqual(world.dominant_cover(Counter({10: 60}), 60, 150, Counter()), 3)  # type unknown: mixed
        self.assertEqual(world.dominant_cover(Counter({30: 60, 40: 40}), 100, 150, ft), 6)  # meadows
        self.assertEqual(world.dominant_cover(Counter({30: 60, 40: 40}), 100, 1200, ft), 5)  # mountain grass
        self.assertEqual(world.dominant_cover(Counter({50: 30, 40: 70}), 100, 150, ft), 9)  # built-up
        self.assertEqual(world.dominant_cover(Counter(), 0, 150, ft), 0)

    def test_land_pct(self):
        p = world.land_pct(Counter({10: 50, 40: 25, 30: 20, 50: 5}), 100, 120)
        self.assertEqual((p["forest"], p["crop"], p["pasture"], p["grass"], p["developed"]), (50, 25, 20, 0, 5))
        self.assertEqual(world.land_pct(Counter({30: 10}), 10, 1000)["grass"], 100)

    def test_river_chains(self):
        line = lambda a, b: [(a, 0.0), (b, 0.0)]
        reaches = [
            {"id": 1, "next": 3, "upland_km2": 500, "line": line(0, 1)},
            {"id": 2, "next": 3, "upland_km2": 2000, "line": line(5, 1)},
            {"id": 3, "next": 0, "upland_km2": 2600, "line": line(1, 2)},
        ]
        chains = world.river_chains(reaches)
        ids = sorted([r["id"] for r in c if not r.get("join")] for c in chains)
        self.assertEqual(ids, [[1], [2, 3]])
        trib = next(c for c in chains if c[0]["id"] == 1)
        self.assertTrue(trib[-1]["join"])

    def test_river_rank(self):
        self.assertEqual(world.river_rank(1050), 1)
        self.assertEqual(world.river_rank(570), 2)
        self.assertEqual(world.river_rank(5), 7)
        self.assertEqual(world.river_rank(None), 9)

    def test_trace_rings(self):
        square = {(r, c) for r in range(3) for c in range(3)}
        rings = world.trace_rings(square)
        self.assertEqual(len(rings), 1)
        self.assertEqual(abs(world.ring_area([(c, r) for r, c in rings[0]])), 9)
        donut = square - {(1, 1)}
        rings = world.trace_rings(donut)
        self.assertEqual(sorted(abs(world.ring_area([(c, r) for r, c in rg])) for rg in rings), [1, 9])
        diag = {(0, 0), (1, 1)}
        self.assertEqual(len(world.components(diag)), 2)
        self.assertEqual(sum(abs(world.ring_area([(c, r) for r, c in rg])) for rg in world.trace_rings(diag)), 2)

    def test_douglas_peucker(self):
        pts = [(0, 0), (1, 0.01), (2, 0), (3, 1)]
        self.assertEqual(world.douglas_peucker(pts, 0.1), [(0, 0), (2, 0), (3, 1)])

    def test_rasterise_in_cells(self):
        g = HexGrid(5.0, 6, 6)
        cell = g.index(2, 2)
        cx, cy = g.center(2, 2)
        box = Shape([[(cx - 1, cy - 1), (cx + 1, cy - 1), (cx + 1, cy + 1), (cx - 1, cy + 1)]])
        px = world.rasterise_in_cells([box], {cell}, g, 0.1)
        self.assertAlmostEqual(len(px) * 0.01, 4.0, delta=0.05)
        far = world.rasterise_in_cells([box], {g.index(0, 0)}, g, 0.1)
        self.assertEqual(far, set())


class StatesTest(unittest.TestCase):
    def test_capitals_checked_against_register(self):
        gminy = {"0461011": "Bydgoszcz", "0463011": "Toruń"}
        caps = states_mod.capitals("04", gminy)
        self.assertEqual([c["name"] for c in caps], ["Bydgoszcz", "Toruń"])
        with self.assertRaises(ValueError):
            states_mod.capitals("04", {"0461011": "Bydgoszcz"})

    def test_every_voivodeship_has_a_capital(self):
        self.assertEqual(sorted(states_mod.CAPITALS), sorted(world.ABBR))

    def test_label_anchor(self):
        g = HexGrid(5.0, 10, 8)
        owner = [0 if 2 <= c <= 7 and 2 <= r <= 5 else -1 for r in range(8) for c in range(10)]
        lab = states_mod.label_anchor(g, owner, 0, "Opolskie")
        self.assertIsNotNone(lab)
        self.assertTrue(states_mod.MIN_LABEL_KM <= lab["size"] <= states_mod.MAX_LABEL_KM)
        self.assertIsNone(states_mod.label_anchor(g, owner, 1, "x"))


if __name__ == "__main__":
    unittest.main()

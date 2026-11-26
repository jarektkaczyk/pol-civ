"""Small standard-library readers for the rasters the geography sources use.

* TIFF / BigTIFF: IFD parsing (little or big endian) and tiled 8-bit decoding with
  no compression, LZW (5) or Deflate (8, 32946), with or without horizontal
  differencing (predictor 2). Enough for Cloud-Optimised GeoTIFFs such as ESA
  WorldCover and the Copernicus Global Land Cover layers.
* ESRI ASCII grids (ERDDAP ``.esriAscii``).

Helpers only: no Source here (the registry ignores modules without one).
"""

from __future__ import annotations

import struct
import zlib

# TIFF field types -> (struct code, size in bytes)
_TYPES = {
    1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 6: ("b", 1), 7: ("B", 1),
    8: ("h", 2), 9: ("i", 4), 10: ("ii", 8), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8), 17: ("q", 8), 18: ("Q", 8),
}

TAG_WIDTH, TAG_HEIGHT, TAG_BPS, TAG_COMPRESSION = 256, 257, 258, 259
TAG_TILE_W, TAG_TILE_H, TAG_TILE_OFFSETS, TAG_TILE_COUNTS = 322, 323, 324, 325
TAG_PREDICTOR, TAG_PIXEL_SCALE, TAG_TIEPOINT = 317, 33550, 33922


class Pointer:
    """A tag value stored outside the bytes we have: read it later with read_values(buf, base, ptr)."""

    def __init__(self, offset: int, count: int, ftype: int, endian: str):
        self.offset, self.count, self.ftype, self.endian = offset, count, ftype, endian

    def __repr__(self) -> str:
        return f"Pointer(offset={self.offset}, count={self.count}, type={self.ftype})"


def _unpack(endian: str, ftype: int, count: int, data: bytes):
    code, size = _TYPES[ftype]
    if ftype == 2:
        return data[:count].split(b"\0", 1)[0].decode("latin-1")
    if ftype in (5, 10):
        vals = struct.unpack(endian + code[0] * (2 * count), data[: size * count])
        return tuple(vals[k] / vals[k + 1] if vals[k + 1] else 0.0 for k in range(0, len(vals), 2))
    return struct.unpack(endian + code * count, data[: size * count])


def read_values(buf: bytes, base: int, ptr: Pointer):
    """Values of a Pointer tag from `buf`, which holds the file's bytes starting at offset `base`."""
    start = ptr.offset - base
    size = _TYPES[ptr.ftype][1] * ptr.count
    if start < 0 or start + size > len(buf):
        raise ValueError(f"{ptr!r} is outside the {len(buf)} bytes at offset {base}")
    return _unpack(ptr.endian, ptr.ftype, ptr.count, buf[start:start + size])


def tiff_header(head: bytes) -> tuple[str, bool, int]:
    """(endian '<' or '>', bigtiff, offset of the first IFD) from the first 16 bytes of a TIFF."""
    if head[:2] == b"II":
        endian = "<"
    elif head[:2] == b"MM":
        endian = ">"
    else:
        raise ValueError("not a TIFF (no II/MM byte order mark)")
    magic = struct.unpack(endian + "H", head[2:4])[0]
    if magic == 42:
        return endian, False, struct.unpack(endian + "I", head[4:8])[0]
    if magic == 43:
        return endian, True, struct.unpack(endian + "Q", head[8:16])[0]
    raise ValueError(f"not a TIFF (magic {magic})")


def read_ifds(buf: bytes, base: int, endian: str, bigtiff: bool, first: int, limit: int = 64) -> list[dict]:
    """Every IFD reachable from offset `first` whose entries lie in `buf` (file bytes from offset `base`).

    Each IFD is {tag: tuple | str | Pointer}; a value that lies outside `buf` is left as a Pointer.
    The chain stops at the first IFD outside `buf`.
    """
    ifds = []
    off = first
    cnt_fmt, cnt_size = ("Q", 8) if bigtiff else ("H", 2)
    ent_size, val_size = (20, 8) if bigtiff else (12, 4)
    while off and len(ifds) < limit:
        p = off - base
        if p < 0 or p + cnt_size > len(buf):
            break
        n = struct.unpack(endian + cnt_fmt, buf[p:p + cnt_size])[0]
        if p + cnt_size + n * ent_size + val_size > len(buf):
            break
        tags = {}
        for k in range(n):
            e = p + cnt_size + k * ent_size
            if bigtiff:
                tag, ftype, count = struct.unpack(endian + "HHQ", buf[e:e + 12])
                raw = buf[e + 12:e + 20]
            else:
                tag, ftype, count = struct.unpack(endian + "HHI", buf[e:e + 8])
                raw = buf[e + 8:e + 12]
            if ftype not in _TYPES:
                continue
            size = _TYPES[ftype][1] * count
            if size <= val_size:
                tags[tag] = _unpack(endian, ftype, count, raw)
            else:
                ptr = Pointer(struct.unpack(endian + ("Q" if bigtiff else "I"), raw)[0], count, ftype, endian)
                start = ptr.offset - base
                tags[tag] = read_values(buf, base, ptr) if 0 <= start and start + size <= len(buf) else ptr
        ifds.append(tags)
        q = p + cnt_size + n * ent_size
        off = struct.unpack(endian + ("Q" if bigtiff else "I"), buf[q:q + val_size])[0]
    return ifds


def lzw_decode(data: bytes) -> bytes:
    """TIFF LZW (MSB-first codes, 9 to 12 bits, early change, 256 = clear, 257 = end of information)."""
    out = bytearray()
    table: list[bytes] = []
    width = 9
    bitbuf = nbits = 0
    prev = None
    pos = 0
    n = len(data)
    while True:
        while nbits < width:
            if pos >= n:
                return bytes(out)
            bitbuf = (bitbuf << 8) | data[pos]
            pos += 1
            nbits += 8
        nbits -= width
        code = (bitbuf >> nbits) & ((1 << width) - 1)
        bitbuf &= (1 << nbits) - 1
        if code == 256:
            table = [bytes([k]) for k in range(256)] + [b"", b""]
            width = 9
            prev = None
            continue
        if code == 257:
            return bytes(out)
        if not table:
            table = [bytes([k]) for k in range(256)] + [b"", b""]
        if prev is None:
            entry = table[code]
            out += entry
            prev = entry
            continue
        if code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        elif code == len(table):
            entry = prev + prev[:1]
            table.append(entry)
        else:
            raise ValueError(f"bad LZW code {code} (table size {len(table)})")
        out += entry
        prev = entry
        # Early change: the code width grows one code before the table fills.
        if len(table) + 1 >= (1 << width) and width < 12:
            width += 1


def undo_horizontal_predictor(data: bytes, width: int) -> bytes:
    """Reverse TIFF predictor 2 for 8-bit, one sample per pixel."""
    out = bytearray(data)
    for r in range(0, len(out), width):
        acc = 0
        for k in range(r, min(r + width, len(out))):
            acc = (acc + out[k]) & 0xFF
            out[k] = acc
    return bytes(out)


def decode_tile(data: bytes, compression: int, predictor: int, tile_w: int, tile_h: int) -> bytes:
    """One 8-bit, single-band tile as tile_w * tile_h bytes (short tiles are zero-padded)."""
    if compression == 1:
        raw = data
    elif compression == 5:
        raw = lzw_decode(data)
    elif compression in (8, 32946):
        raw = zlib.decompress(data)
    else:
        raise ValueError(f"unsupported TIFF compression {compression}")
    if predictor == 2:
        raw = undo_horizontal_predictor(raw, tile_w)
    elif predictor not in (0, 1):
        raise ValueError(f"unsupported TIFF predictor {predictor}")
    need = tile_w * tile_h
    return raw[:need] if len(raw) >= need else raw + bytes(need - len(raw))


def ifd_int(ifd: dict, tag: int, default: int | None = None) -> int:
    v = ifd.get(tag)
    if v is None:
        if default is None:
            raise KeyError(f"TIFF tag {tag} missing")
        return default
    return int(v[0])


def parse_esri_ascii(text: str) -> dict:
    """ESRI ASCII grid -> {ncols, nrows, xll, yll (lower-left cell centre), cellsize, nodata, rows (north first)}.

    Accepts both corner (xllcorner) and centre (xllcenter) headers; values become floats, nodata None.
    """
    lines = text.splitlines()
    head: dict[str, float] = {}
    k = 0
    while k < len(lines):
        parts = lines[k].split()
        if len(parts) == 2 and parts[0].replace("_", "").isalpha():
            head[parts[0].lower()] = float(parts[1])
            k += 1
        else:
            break
    ncols, nrows, cs = int(head["ncols"]), int(head["nrows"]), head["cellsize"]
    xll = head["xllcenter"] if "xllcenter" in head else head["xllcorner"] + cs / 2
    yll = head["yllcenter"] if "yllcenter" in head else head["yllcorner"] + cs / 2
    nodata = head.get("nodata_value")
    rows = []
    for line in lines[k:]:
        vals = line.split()
        if not vals:
            continue
        rows.append([None if (nodata is not None and float(v) == nodata) else float(v) for v in vals])
    if len(rows) != nrows or any(len(r) != ncols for r in rows):
        raise ValueError(f"ESRI ASCII grid: expected {nrows}x{ncols}, got {len(rows)} rows")
    return {"ncols": ncols, "nrows": nrows, "xll": xll, "yll": yll, "cellsize": cs, "nodata": nodata, "rows": rows}

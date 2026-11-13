#!/usr/bin/env python3
"""Wrap a film scan in a raw DNG posing as a Panasonic DMC-G7, for DxO PureRAW.

DxO PureRAW opens camera raw files only. The script upscales the scan 3 times,
converts it to G7 camera colour, mosaics it into a Bayer pattern, and writes an
uncompressed 16-bit DNG. It then decodes the file with rawpy and stops on any
mismatch. It prints the photo size, which is the size of the DxO output.

Each constant came from a DxO test:
    CAM_XYZ, CFA  DxO applies its own G7 calibration. A neutral matrix gave
                  oversaturated colour.
    WB            Daylight, derived from CAM_XYZ. The script divides by it and the
                  raw converter multiplies it back, so it cancels out.
    HEADROOM      DxO clips above about 0.743 of the range, and Smart Lighting then
                  makes white specks. At 0.7, DxO output is 0.7 times as bright as
                  the scan. Restore it with +0.5 EV.
    PAD_*         DxO always crops the G7 sensor margins and ignores DefaultCrop.
                  Black padding fills the margins. Windows Photos ignores
                  DefaultCrop and shows the padding.
    SCALE         3 times cuts colour fringes by half against 2 times. 4 times adds
                  little. Lanczos gives half the colour error of --nearest.
    BLACK, WHITE  The G7 levels, 143 and 4095, at 16 bits.

The raw data sits in IFD0, because the Windows DNG decoder reads IFD0 only. DxO
rejects a LinearRaw DNG and ignores BaselineExposure. Windows ignores
ProfileToneCurve. A viewer shows more contrast than the scan, because it applies
its own tone curve to a raw file.
"""

from __future__ import annotations

import argparse
import io
import struct
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image, ImageCms, ImageOps

SCALE = 3
HEADROOM = 0.7
PAD_TOP, PAD_LEFT, PAD_BOTTOM, PAD_RIGHT = 8, 8, 8, 216
MAKE, MODEL = "Panasonic", "DMC-G7"
CFA = np.array([[2, 1], [1, 0]])
BLACK, WHITE = 2288, 65520
CAM_XYZ = np.array([[7610, -2780, -576], [-4614, 12195, 2733], [-1375, 2393, 6490]]) / 10000
DATE = "2000:01:01 00:00:00"
EXIF = [(33434, 5, [1, 125]), (33437, 5, [8, 1]), (34855, 3, 200), (36864, 7, b"0230"),
        (36867, 2, DATE), (36868, 2, DATE), (37381, 5, [2, 1]), (37386, 5, [50, 1]), (41989, 3, 50)]
XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423],
                    [0.212671, 0.715160, 0.072169],
                    [0.019334, 0.119193, 0.950227]])
FMT = {1: "B", 3: "H", 4: "I", 5: "I", 7: "B", 10: "i"}

CAM_RGB = CAM_XYZ @ XYZ_RGB
WB = 1 / CAM_RGB.sum(1)
WB /= WB[1]
CAM_RGB /= CAM_RGB.sum(1, keepdims=True)


def mosaic(scan: Path, nearest: bool) -> tuple[np.ndarray, int, int]:
    src = ImageOps.exif_transpose(Image.open(scan))
    if src.info.get("icc_profile"):
        src = ImageCms.profileToProfile(src, ImageCms.ImageCmsProfile(io.BytesIO(src.info["icc_profile"])),
                                        ImageCms.createProfile("sRGB"), outputMode="RGB")
    src = src.convert("RGB")
    w, h = src.width * SCALE, src.height * SCALE
    img = np.asarray(src.resize((w, h), Image.NEAREST if nearest else Image.LANCZOS), np.float32) / 255
    lin = np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4)
    cam = np.clip(lin @ CAM_RGB.T.astype(np.float32) / WB.astype(np.float32), 0, 1) * HEADROOM
    cam = np.pad(cam, ((PAD_TOP, PAD_BOTTOM), (PAD_LEFT, PAD_RIGHT), (0, 0)))
    H, W = cam.shape[:2]
    c = np.tile(CFA, (H // 2 + 1, W // 2 + 1))[:H, :W]
    raw = (BLACK + np.rint(np.take_along_axis(cam, c[..., None], 2)[..., 0] * (WHITE - BLACK))).astype("<u2")
    return raw, w, h


def tag(code: int, typ: int, values) -> tuple[int, int, int, bytes]:
    if typ == 2:
        data = values.encode() + b"\x00"
        return code, typ, len(data), data
    if isinstance(values, bytes):
        return code, typ, len(values), values
    values = values if isinstance(values, list) else [values]
    return code, typ, len(values) // (2 if typ in (5, 10) else 1), struct.pack(f"<{len(values)}{FMT[typ]}", *values)


def ifd(entries: list, at: int) -> bytes:
    entries = sorted(entries)
    ext_at = at + 2 + 12 * len(entries) + 4
    head, ext = struct.pack("<H", len(entries)), b""
    for code, typ, n, data in entries:
        if len(data) <= 4:
            head += struct.pack("<HHI", code, typ, n) + data.ljust(4, b"\x00")
        else:
            head += struct.pack("<HHII", code, typ, n, ext_at + len(ext))
            ext += data + b"\x00" * (len(data) % 2)
    return head + struct.pack("<I", 0) + ext


def build(raw: np.ndarray, w: int, h: int, exif_at: int, raw_at: int) -> tuple[bytes, bytes]:
    H, W = raw.shape
    ifd0 = [tag(254, 4, 0), tag(256, 4, W), tag(257, 4, H), tag(258, 3, 16), tag(259, 3, 1), tag(262, 3, 32803),
            tag(271, 2, MAKE), tag(272, 2, MODEL), tag(273, 4, raw_at), tag(274, 3, 1),
            tag(277, 3, 1), tag(278, 4, H), tag(279, 4, raw.nbytes), tag(284, 3, 1), tag(306, 2, DATE),
            tag(33421, 3, [2, 2]), tag(33422, 1, [int(x) for x in CFA.ravel()]),
            tag(34665, 4, exif_at), tag(50706, 1, [1, 4, 0, 0]), tag(50707, 1, [1, 1, 0, 0]),
            tag(50708, 2, f"{MAKE} {MODEL}"), tag(50710, 1, [0, 1, 2]), tag(50711, 3, 1),
            tag(50713, 3, [1, 1]), tag(50714, 4, BLACK), tag(50717, 4, WHITE), tag(50718, 5, [1, 1, 1, 1]),
            tag(50719, 4, [PAD_LEFT, PAD_TOP]), tag(50720, 4, [w, h]),
            tag(50721, 10, [v for x in CAM_XYZ.ravel() for v in (round(x * 10000), 10000)]),
            tag(50728, 5, [v for x in 1 / WB for v in (round(x * 1000000), 1000000)]),
            tag(50778, 3, 21), tag(50829, 4, [0, 0, H, W])]
    exif = [tag(code, typ, v) for code, typ, v in EXIF]
    a = ifd(ifd0, 8)
    return a, ifd(exif, 8 + len(a))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wrap a scan in a raw DNG posing as a Panasonic DMC-G7, for DxO PureRAW.")
    parser.add_argument("scan", type=Path, help="input image (JPEG, PNG, ...)")
    parser.add_argument("output", type=Path, help="output DNG (must not exist)")
    parser.add_argument("--nearest", action="store_true", help="upscale by pixel duplication instead of Lanczos")
    opts = parser.parse_args()

    raw, w, h = mosaic(opts.scan, opts.nearest)
    H, W = raw.shape
    a, e = build(raw, w, h, 0, 0)
    exif_at, raw_at = 8 + len(a), 8 + len(a) + len(e)
    a, e = build(raw, w, h, exif_at, raw_at)
    assert exif_at == 8 + len(a) and raw_at == exif_at + len(e)
    with open(opts.output, "xb") as f:
        f.write(b"II*\x00" + struct.pack("<I", 8) + a + e + raw.tobytes())

    with rawpy.imread(str(opts.output)) as r:
        assert r.raw_image.shape == (H, W) and np.array_equal(r.raw_image, raw), "LibRaw decode mismatch"
        assert r.color_desc == b"RGBG" and np.array_equal(np.array([0, 1, 2, 1])[r.raw_pattern], CFA)
    print(f"{w}x{h} DNG ({W}x{H} with the G7 margins DxO crops)")


if __name__ == "__main__":
    main()

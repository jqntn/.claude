import argparse
import io
import struct

import numpy as np
import rawpy
from PIL import Image, ImageCms, ImageOps

parser = argparse.ArgumentParser(description="Wrap a scan in a raw DNG posing as a Panasonic DMC-G7, for DxO PureRAW.")
parser.add_argument("scan", help="input image (JPEG, PNG, ...)")
parser.add_argument("output", help="output DNG (must not exist)")
parser.add_argument("--nearest", action="store_true", help="upscale by pixel duplication instead of Lanczos")
args = parser.parse_args()

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

xyz_rgb = np.array([[0.412453, 0.357580, 0.180423],
                    [0.212671, 0.715160, 0.072169],
                    [0.019334, 0.119193, 0.950227]])
cam_rgb = CAM_XYZ @ xyz_rgb
WB = 1 / cam_rgb.sum(1)
WB /= WB[1]
cam_rgb /= cam_rgb.sum(1, keepdims=True)

src = ImageOps.exif_transpose(Image.open(args.scan))
if src.info.get("icc_profile"):
    src = ImageCms.profileToProfile(src, ImageCms.ImageCmsProfile(io.BytesIO(src.info["icc_profile"])),
                                    ImageCms.createProfile("sRGB"), outputMode="RGB")
src = src.convert("RGB")
w, h = src.width * SCALE, src.height * SCALE
img = np.asarray(src.resize((w, h), Image.NEAREST if args.nearest else Image.LANCZOS), np.float32) / 255
lin = np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4)
cam = np.clip(lin @ cam_rgb.T.astype(np.float32) / WB.astype(np.float32), 0, 1) * HEADROOM
cam = np.pad(cam, ((PAD_TOP, PAD_BOTTOM), (PAD_LEFT, PAD_RIGHT), (0, 0)))
H, W = cam.shape[:2]
c = np.tile(CFA, (H // 2 + 1, W // 2 + 1))[:H, :W]
raw = (BLACK + np.rint(np.take_along_axis(cam, c[..., None], 2)[..., 0] * (WHITE - BLACK))).astype("<u2")

FMT = {1: "B", 3: "H", 4: "I", 5: "I", 7: "B", 10: "i"}


def tag(code, typ, values):
    if typ == 2:
        data = values.encode() + b"\x00"
        return code, typ, len(data), data
    if isinstance(values, bytes):
        return code, typ, len(values), values
    values = values if isinstance(values, list) else [values]
    return code, typ, len(values) // (2 if typ in (5, 10) else 1), struct.pack(f"<{len(values)}{FMT[typ]}", *values)


def ifd(entries, at):
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


def build(o):
    ifd0 = [tag(254, 4, 0), tag(256, 4, W), tag(257, 4, H), tag(258, 3, 16), tag(259, 3, 1), tag(262, 3, 32803),
            tag(271, 2, MAKE), tag(272, 2, MODEL), tag(273, 4, o["raw"]), tag(274, 3, 1),
            tag(277, 3, 1), tag(278, 4, H), tag(279, 4, raw.nbytes), tag(284, 3, 1), tag(306, 2, DATE),
            tag(33421, 3, [2, 2]), tag(33422, 1, [int(x) for x in CFA.ravel()]),
            tag(34665, 4, o["exif"]), tag(50706, 1, [1, 4, 0, 0]), tag(50707, 1, [1, 1, 0, 0]),
            tag(50708, 2, f"{MAKE} {MODEL}"), tag(50710, 1, [0, 1, 2]), tag(50711, 3, 1),
            tag(50713, 3, [1, 1]), tag(50714, 4, BLACK), tag(50717, 4, WHITE), tag(50718, 5, [1, 1, 1, 1]),
            tag(50719, 4, [PAD_LEFT, PAD_TOP]), tag(50720, 4, [w, h]),
            tag(50721, 10, [v for x in CAM_XYZ.ravel() for v in (round(x * 10000), 10000)]),
            tag(50728, 5, [v for x in 1 / WB for v in (round(x * 1000000), 1000000)]),
            tag(50778, 3, 21), tag(50829, 4, [0, 0, H, W])]
    exif = [tag(code, typ, v) for code, typ, v in EXIF]
    a = ifd(ifd0, 8)
    return a, ifd(exif, 8 + len(a))


a, e = build(dict(exif=0, raw=0))
o = dict(exif=8 + len(a), raw=8 + len(a) + len(e))
a, e = build(o)
assert o["exif"] == 8 + len(a) and o["raw"] == o["exif"] + len(e)
open(args.output, "xb").write(b"II*\x00" + struct.pack("<I", 8) + a + e + raw.tobytes())

with rawpy.imread(args.output) as r:
    assert r.raw_image.shape == (H, W) and np.array_equal(r.raw_image, raw), "LibRaw decode mismatch"
    assert r.color_desc == b"RGBG" and np.array_equal(np.array([0, 1, 2, 1])[r.raw_pattern], CFA)
print(f"{w}x{h} DNG ({W}x{H} with the G7 margins DxO crops)")

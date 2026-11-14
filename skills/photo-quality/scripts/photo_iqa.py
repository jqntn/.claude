#!/usr/bin/env python3
"""Rank photos on technical quality, aesthetics and sharpness with pyiqa.

Each axis is a z-score across the files of one folder.

axes:
  tech   mean z-score of topiq_nr, musiq, niqe, brisque
  aesth  mean z-score of topiq_iaa, nima, laion_aes, clipiqa+
  sharp  z-score of the Laplacian variance of the sharpest tile

niqe and brisque are lower-better, so the script negates their z-score before the
mean. sharp runs a 6x6 grid at native resolution and keeps the highest tile
variance. mean averages the three axes. worst takes their minimum.

A raw file decodes through rawpy at half size with camera white balance. The
models read a copy resized to --long-edge. The Laplacian reads the full frame.

examples:
  Rank one folder, and write the CSV into it:
    photo_iqa.py IN

  Copy the 4 best files:
    photo_iqa.py IN OUT --top 4

  Copy every file with no weak axis:
    photo_iqa.py IN OUT --rank-by worst --min-score 0.2
"""

import argparse
import csv
import importlib.util
import shutil
import sys
import types
from operator import itemgetter
from pathlib import Path

import cv2
import numpy as np
import packaging.version
import rawpy
import torch

RAW_EXTS = {
    ".rw2",
    ".raw",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".orf",
    ".raf",
    ".dng",
    ".pef",
    ".srw",
}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
TECH = ["topiq_nr", "musiq", "niqe", "brisque"]
AESTH = ["topiq_iaa", "nima", "laion_aes", "clipiqa+"]
AXES = ["tech", "aesth", "sharp"]
KEYS = [*AXES, "mean", "worst"]


def load_rgb(path: Path) -> np.ndarray:
    if path.suffix.lower() in RAW_EXTS:
        with rawpy.imread(str(path)) as raw:
            return raw.postprocess(
                use_camera_wb=True, half_size=True, no_auto_bright=False, output_bps=8
            )
    buf = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None
    if img is None:
        sys.exit(f"error: cannot read {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def resize_long(img: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = long_edge / max(h, w)
    if scale >= 1:
        return img
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


def tile_max(img: np.ndarray, grid: int = 6) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    th, tw = gray.shape[0] // grid, gray.shape[1] // grid
    tiles = (
        gray[y * th : (y + 1) * th, x * tw : (x + 1) * tw]
        for y in range(grid)
        for x in range(grid)
    )
    return max(float(cv2.Laplacian(t, cv2.CV_64F).var()) for t in tiles)


def zscore(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    sd = arr.std()
    return np.zeros_like(arr) if sd == 0 else (arr - arr.mean()) / sd


def load_models(names: list[str], device: str) -> dict:
    if importlib.util.find_spec("pkg_resources") is None:
        shim = types.ModuleType("pkg_resources")
        shim.packaging = packaging
        sys.modules["pkg_resources"] = shim
    import pyiqa

    models = {}
    for name in names:
        try:
            models[name] = pyiqa.create_metric(name, device=device)
        except Exception as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)
    return models


def score(
    files: list[Path], models: dict, long_edge: int, device: str, *, quiet: bool
) -> list[dict]:
    rows = []
    for i, path in enumerate(files, 1):
        img = load_rgb(path)
        tensor = (
            torch.from_numpy(resize_long(img, long_edge))
            .permute(2, 0, 1)
            .float()
            .div_(255)
            .unsqueeze(0)
            .to(device)
        )
        row = {"file": path.name, "lap_tile_max": tile_max(img)}
        with torch.no_grad():
            for name, model in models.items():
                row[name] = float(model(tensor).item())
        rows.append(row)
        if not quiet:
            print(f"[{i}/{len(files)}] {path.name}", flush=True)
    return rows


def add_axes(rows: list[dict], models: dict) -> None:
    for axis, group in (("tech", TECH), ("aesth", AESTH)):
        active = [n for n in group if n in models]
        total = np.zeros(len(rows))
        for name in active:
            z = zscore([r[name] for r in rows])
            total += -z if models[name].lower_better else z
        for row, value in zip(rows, total, strict=True):
            row[axis] = value / len(active) if active else 0.0
    for row, value in zip(rows, zscore([r["lap_tile_max"] for r in rows]), strict=True):
        row["sharp"] = value
    for row in rows:
        row["mean"] = sum(row[a] for a in AXES) / len(AXES)
        row["worst"] = min(row[a] for a in AXES)


def write_csv(path: Path, rows: list[dict], models: dict) -> None:
    loaded = [n for n in TECH + AESTH if n in models]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["rank", "file", *KEYS, "lap_tile_max", *loaded],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows({"rank": i, **row} for i, row in enumerate(rows, 1))
    print(f"wrote {path}")


def print_summary(rows: list[dict], models: dict, key: str) -> None:
    width = max(len(r["file"]) for r in rows)
    print(f"\n{'#':>3} {'file':<{width}}" + "".join(f"{k:>7}" for k in KEYS))
    for i, row in enumerate(rows, 1):
        print(
            f"{i:>3} {row['file']:<{width}}" + "".join(f"{row[k]:>7.2f}" for k in KEYS)
        )
    laps = [r["lap_tile_max"] for r in rows]
    spread = max(laps) / min(laps) if min(laps) > 0 else float("inf")
    print(f"\nsharpness {min(laps):.0f} to {max(laps):.0f}, spread {spread:.2f}x")
    missing = [n for n in TECH + AESTH if n not in models]
    if missing:
        print(f"metrics that failed to load: {', '.join(missing)}")
    print(f"sorted by {key}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("indir", type=Path, help="folder that holds the photos")
    parser.add_argument(
        "outdir",
        type=Path,
        nargs="?",
        help="folder to copy the best files into, created if missing",
    )
    parser.add_argument(
        "--rank-by",
        choices=KEYS,
        default="mean",
        help="sort key (default: %(default)s)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        help="copy only the files whose sort value reaches this value",
    )
    parser.add_argument("--top", type=int, help="copy only the N best files")
    parser.add_argument(
        "--metrics",
        default=",".join(TECH + AESTH),
        help="comma-separated pyiqa metrics to run (default: all eight)",
    )
    parser.add_argument(
        "--long-edge",
        type=int,
        default=1536,
        help="resize the long edge to this many pixels before the models "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--device",
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="torch device (default: %(default)s)",
    )
    parser.add_argument(
        "--csv-name",
        default="pyiqa_ranking.csv",
        help="name of the CSV file (default: %(default)s)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="hide the progress for each file",
    )
    args = parser.parse_args()

    if not args.indir.is_dir():
        sys.exit(f"error: input folder not found: {args.indir}")
    files = sorted(
        p
        for p in args.indir.iterdir()
        if p.is_file() and p.suffix.lower() in RAW_EXTS | IMG_EXTS
    )
    if not files:
        sys.exit(f"error: no matching images in {args.indir}")

    names = [m.strip() for m in args.metrics.split(",") if m.strip()]
    models = load_models(names, args.device)
    rows = score(files, models, args.long_edge, args.device, quiet=args.quiet)
    add_axes(rows, models)
    rows.sort(key=itemgetter(args.rank_by), reverse=True)

    out = args.outdir or args.indir
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / args.csv_name, rows, models)
    print_summary(rows, models, args.rank_by)

    if not args.outdir:
        return
    keep = rows
    if args.min_score is not None:
        keep = [r for r in keep if r[args.rank_by] >= args.min_score]
    if args.top is not None:
        keep = keep[: args.top]
    for i, row in enumerate(keep, 1):
        src = args.indir / row["file"]
        shutil.copy2(src, out / f"{i:02d}_{row[args.rank_by]:+.2f}_{src.name}")
    print(f"\ncopied {len(keep)} file(s) to {out}")


if __name__ == "__main__":
    main()

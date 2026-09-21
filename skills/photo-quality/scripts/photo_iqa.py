#!/usr/bin/env python3
"""Rank photos on three axes with pyiqa.

Each axis is a z-score across the files of one folder.

    tech   mean z-score of topiq_nr, musiq, niqe, brisque
    aesth  mean z-score of topiq_iaa, nima, laion_aes, clipiqa+
    sharp  z-score of the laplacian variance of the sharpest tile

niqe and brisque are lower-better, so the script negates their z-score before the
mean. sharp runs a 6x6 grid at native resolution and keeps the highest tile
variance. mean averages the three axes. worst takes their minimum.

A raw file decodes through rawpy at half size with camera white balance. The
models read a copy resized to --long-edge. The laplacian reads the full frame.

Usage
    python photo_iqa.py IN
    python photo_iqa.py IN OUT --top 4
    python photo_iqa.py IN OUT --rank-by worst --min-score 0.2
"""

import argparse
import csv
import importlib.util
import shutil
import sys
import types
from pathlib import Path

import packaging
import packaging.version

if importlib.util.find_spec("pkg_resources") is None:
    _shim = types.ModuleType("pkg_resources")
    _shim.packaging = packaging
    sys.modules["pkg_resources"] = _shim

import cv2
import numpy as np
import torch

RAW_EXT = {".rw2", ".raw", ".arw", ".cr2", ".cr3", ".nef", ".dng", ".orf", ".raf"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
TECH = ["topiq_nr", "musiq", "niqe", "brisque"]
AESTH = ["topiq_iaa", "nima", "laion_aes", "clipiqa+"]
AXES = ["tech", "aesth", "sharp"]


def load_rgb(path):
    if path.suffix.lower() in RAW_EXT:
        import rawpy

        with rawpy.imread(str(path)) as raw:
            return raw.postprocess(
                use_camera_wb=True, half_size=True, no_auto_bright=False, output_bps=8
            )
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def resize_long(img, long_edge):
    h, w = img.shape[:2]
    scale = long_edge / max(h, w)
    if scale >= 1.0:
        return img
    return cv2.resize(
        img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA
    )


def laplacian_tile_max(img, tiles=6):
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    th, tw = h // tiles, w // tiles
    best = 0.0
    for i in range(tiles):
        for j in range(tiles):
            tile = gray[i * th : (i + 1) * th, j * tw : (j + 1) * tw]
            best = max(best, float(cv2.Laplacian(tile, cv2.CV_64F).var()))
    return best


def zscore(values):
    arr = np.asarray(values, dtype=float)
    sd = arr.std()
    if sd == 0:
        return np.zeros_like(arr)
    return (arr - arr.mean()) / sd


def list_images(indir):
    return sorted(
        p
        for p in indir.iterdir()
        if p.is_file() and p.suffix.lower() in RAW_EXT | IMG_EXT
    )


def score_folder(indir, metrics, long_edge, device, quiet):
    import pyiqa

    files = list_images(indir)
    if not files:
        sys.exit(f"no image in {indir}")

    models = {}
    for name in metrics:
        try:
            models[name] = pyiqa.create_metric(name, device=device)
        except Exception as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)

    rows = []
    for k, path in enumerate(files, 1):
        img = load_rgb(path)
        tensor = (
            torch.from_numpy(resize_long(img, long_edge))
            .permute(2, 0, 1)
            .float()
            .div_(255.0)
            .unsqueeze(0)
            .to(device)
        )
        row = {"file": path.name, "lap_tile_max": laplacian_tile_max(img)}
        for name, model in models.items():
            with torch.no_grad():
                row[name] = float(model(tensor).item())
        rows.append(row)
        if not quiet:
            print(f"[{k}/{len(files)}] {path.name}", flush=True)

    return rows, models


def add_axes(rows, models):
    for axis, group in (("tech", TECH), ("aesth", AESTH)):
        active = [n for n in group if n in models]
        if not active:
            for row in rows:
                row[axis] = 0.0
            continue
        total = np.zeros(len(rows))
        for name in active:
            z = zscore([r[name] for r in rows])
            if models[name].lower_better:
                z = -z
            total += z
        for row, value in zip(rows, total):
            row[axis] = value / len(active)

    for row, value in zip(rows, zscore([r["lap_tile_max"] for r in rows])):
        row["sharp"] = value

    for row in rows:
        row["mean"] = sum(row[a] for a in AXES) / len(AXES)
        row["worst"] = min(row[a] for a in AXES)


def report(rows, models, key):
    width = max(len(r["file"]) for r in rows)
    head = f"{'#':>3} {'file':<{width}}" + "".join(
        f"{a:>7}" for a in AXES + ["mean", "worst"]
    )
    print("\n" + head)
    for i, row in enumerate(rows, 1):
        line = f"{i:>3} {row['file']:<{width}}" + "".join(
            f"{row[a]:>7.2f}" for a in AXES + ["mean", "worst"]
        )
        print(line)

    laps = [r["lap_tile_max"] for r in rows]
    spread = max(laps) / min(laps) if min(laps) > 0 else float("inf")
    print(f"\nsharpness {min(laps):.0f} to {max(laps):.0f}, spread {spread:.2f}x")
    missing = [n for n in TECH + AESTH if n not in models]
    if missing:
        print(f"metrics that failed to load: {', '.join(missing)}")
    print(f"sorted by {key}")


def write_csv(path, rows, models):
    names = [n for n in TECH + AESTH if n in models]
    cols = ["rank", "file"] + AXES + ["mean", "worst", "lap_tile_max"] + names
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            writer.writerow({"rank": i, **{c: row.get(c) for c in cols if c != "rank"}})
    print(f"wrote {path}")


def main():
    ap = argparse.ArgumentParser(
        description="Rank photos on technical quality, aesthetics and sharpness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("indir", help="folder of photos to score")
    ap.add_argument("outdir", nargs="?", help="folder to copy the keepers into")
    ap.add_argument(
        "--rank-by",
        default="mean",
        choices=AXES + ["mean", "worst"],
        help="sort key, default mean",
    )
    ap.add_argument(
        "--top", type=int, default=0, help="copy this many files, 0 copies every file"
    )
    ap.add_argument(
        "--min-score", type=float, help="copy only files at or above this sort value"
    )
    ap.add_argument(
        "--metrics",
        default=",".join(TECH + AESTH),
        help="pyiqa metrics to run, comma separated",
    )
    ap.add_argument(
        "--long-edge", type=int, default=1536, help="resize before the models, default 1536"
    )
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--csv-name", default="pyiqa_ranking.csv")
    ap.add_argument("--quiet", action="store_true", help="hide the per file progress")
    args = ap.parse_args()

    indir = Path(args.indir)
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    rows, models = score_folder(
        indir, metrics, args.long_edge, args.device, args.quiet
    )
    add_axes(rows, models)
    rows.sort(key=lambda r: r[args.rank_by], reverse=True)

    out = Path(args.outdir) if args.outdir else indir
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / args.csv_name, rows, models)
    report(rows, models, args.rank_by)

    if not args.outdir:
        return

    keep = rows
    if args.min_score is not None:
        keep = [r for r in keep if r[args.rank_by] >= args.min_score]
    if args.top:
        keep = keep[: args.top]
    for i, row in enumerate(keep, 1):
        src = indir / row["file"]
        shutil.copy2(src, out / f"{i:02d}_{row[args.rank_by]:+.2f}_{src.name}")
    print(f"\ncopied {len(keep)} file(s) to {out}")


if __name__ == "__main__":
    main()

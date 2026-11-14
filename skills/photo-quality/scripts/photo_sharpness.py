#!/usr/bin/env python3
"""Score photos by sharpness, then copy them renamed with the score.

The script names every copy SCORE__ORIGINALNAME.ext, and it pads the score with
zeros. A file manager then sorts the output folder from the sharpest photo to the
blurriest one. The script also writes scores.csv, which holds all four metrics for
every file.

metrics:
  laplacian   Variance of the Laplacian over the whole frame (Pech-Pacheco, 2000).
              This is the standard no-reference blur measure. A high score means
              sharp, and a low score means blurry.
  tile-max    The same variance, measured for each tile of a grid. The highest
              tile wins. Use it for wildlife, because a blurred background cannot
              lower the score of a sharp subject.
  tenengrad   Mean of the squared Sobel gradient (Tenenbaum, 1970). It reacts less
              to sensor noise. The numbers run about 50 times larger.
  brightness  Mean gray value, 0 to 255. This is a diagnostic, not a sharpness
              score. It goes into scores.csv only, never into a filename.

A score carries no absolute meaning. It moves with the camera, the lens, the
subject and the options below. Rank the files inside one set. A raw file and a JPG
sit on different scales, because the camera sharpens a JPG and leaves a raw file
alone.

The script reads JPG, PNG, TIFF, BMP and WEBP through OpenCV, and raw files through
rawpy.

examples:
  Score one folder and copy every file, the sharpest first:
    photo_sharpness.py IN OUT

  Rank birds by subject sharpness, and keep the 50 best files:
    photo_sharpness.py IN OUT --metric tile-max --top 50

  Score a whole library, and write scores.csv only:
    photo_sharpness.py IN OUT --recursive --dry-run

  Drop the worst files, after you read scores.csv:
    photo_sharpness.py IN OUT --min-score 36

output:
  OUT/00166.78__P1040528.JPG   the copy, renamed with the score
  OUT/scores.csv               rank, file, laplacian, tile_max, tenengrad, brightness

  The script prints percentiles of the whole input set. Use them to choose a value
  for --min-score.
"""

import argparse
import csv
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import rawpy

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
METRICS = ["laplacian", "tile-max", "tenengrad"]


@dataclass
class Result:
    path: Path
    laplacian: float = 0.0
    tile_max: float = 0.0
    tenengrad: float = 0.0
    brightness: float = 0.0
    error: str = ""


def load_gray(path: Path) -> np.ndarray | None:
    if path.suffix.lower() in RAW_EXTS:
        try:
            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(
                    half_size=True,
                    no_auto_bright=True,
                    use_camera_wb=True,
                    output_bps=8,
                    user_flip=0,
                )
        except (rawpy.LibRawError, OSError):
            return None
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE) if buf.size else None


def resize_long(img: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = long_edge / max(h, w)
    if scale >= 1:
        return img
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


def tile_max(lap: np.ndarray, grid: int) -> float:
    h, w = lap.shape
    tiles = (
        lap[y * h // grid : (y + 1) * h // grid, x * w // grid : (x + 1) * w // grid]
        for y in range(grid)
        for x in range(grid)
    )
    return max((float(t.var()) for t in tiles if t.size), default=0.0)


def score_file(path: Path, long_edge: int, grid: int) -> Result:
    gray = load_gray(path)
    if gray is None:
        return Result(path, error="unreadable")
    gray = resize_long(gray, long_edge)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    lap = cv2.Laplacian(blurred, cv2.CV_64F)
    gx = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)
    return Result(
        path,
        laplacian=float(lap.var()),
        tile_max=tile_max(lap, grid),
        tenengrad=float(np.mean(gx * gx + gy * gy)),
        brightness=float(gray.mean()),
    )


def pick(result: Result, metric: str) -> float:
    return getattr(result, metric.replace("-", "_"))


def write_csv(path: Path, ok: list[Result], bad: list[Result]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "rank",
                "file",
                "laplacian",
                "tile_max",
                "tenengrad",
                "brightness",
                "error",
            ]
        )
        writer.writerows(
            [
                rank,
                r.path.name,
                f"{r.laplacian:.4f}",
                f"{r.tile_max:.4f}",
                f"{r.tenengrad:.4f}",
                f"{r.brightness:.2f}",
                "",
            ]
            for rank, r in enumerate(ok, 1)
        )
        writer.writerows(["", r.path.name, "", "", "", "", r.error] for r in bad)


def print_summary(scores: list[float], metric: str, failed: int) -> None:
    print()
    print(f"metric   : {metric}")
    print(f"scored   : {len(scores)} ok, {failed} failed")
    if scores:
        print(f"range    : {min(scores):.2f} .. {max(scores):.2f}")
        print(f"median   : {np.median(scores):.2f}")
        for q in (10, 25, 50, 75, 90):
            print(f"  p{q:<3}   : {np.percentile(scores, q):.2f}")


def copy_ranked(keep: list[Result], outdir: Path, metric: str) -> None:
    for r in keep:
        stem = f"{min(pick(r, metric), 99999.99):08.2f}__{r.path.stem}"
        dest = outdir / f"{stem}{r.path.suffix}"
        n = 1
        while dest.exists():
            dest = outdir / f"{stem}_{n}{r.path.suffix}"
            n += 1
        shutil.copy2(r.path, dest)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("indir", type=Path, help="folder that holds the photos")
    parser.add_argument(
        "outdir",
        type=Path,
        help="folder for the renamed copies and scores.csv, created if missing",
    )
    parser.add_argument(
        "--metric",
        choices=METRICS,
        default="laplacian",
        help="score that goes into the copy filename (default: %(default)s)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="also search every subfolder of the input folder",
    )
    parser.add_argument(
        "--long-edge",
        type=int,
        default=1000,
        help="downscale the long edge to this many pixels before the measurement, "
        "so the scores compare across image sizes (default: %(default)s)",
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=4,
        help="grid size for tile-max. A larger grid finds a smaller subject, but "
        "it also reacts more to noise (default: %(default)s)",
    )
    parser.add_argument(
        "--ext",
        default=",".join(sorted(IMG_EXTS | RAW_EXTS)),
        help="comma-separated file extensions to read (default: %(default)s)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        help="copy only the files whose score reaches this value",
    )
    parser.add_argument("--top", type=int, help="copy only the N best files")
    parser.add_argument(
        "--workers",
        type=int,
        help="number of parallel processes (default: CPU count)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write scores.csv and the summary, and copy no file",
    )
    args = parser.parse_args()

    if not args.indir.is_dir():
        sys.exit(f"error: input folder not found: {args.indir}")
    exts = {e if e.startswith(".") else "." + e for e in args.ext.lower().split(",")}
    found = args.indir.rglob("*") if args.recursive else args.indir.glob("*")
    files = sorted(p for p in found if p.is_file() and p.suffix.lower() in exts)
    if not files:
        sys.exit(f"error: no matching images in {args.indir}")

    print(f"scoring {len(files)} images ...", flush=True)
    n = len(files)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = pool.map(
            score_file, files, [args.long_edge] * n, [args.grid] * n, chunksize=4
        )
        results = []
        for i, result in enumerate(jobs, 1):
            results.append(result)
            if i % 25 == 0 or i == n:
                print(f"  {i}/{n}", flush=True)

    ok = sorted(
        (r for r in results if not r.error),
        key=lambda r: pick(r, args.metric),
        reverse=True,
    )
    bad = [r for r in results if r.error]
    args.outdir.mkdir(parents=True, exist_ok=True)
    report = args.outdir / "scores.csv"
    write_csv(report, ok, bad)

    keep = ok
    if args.min_score is not None:
        keep = [r for r in keep if pick(r, args.metric) >= args.min_score]
    if args.top is not None:
        keep = keep[: args.top]
    if args.dry_run:
        keep = []
    copy_ranked(keep, args.outdir, args.metric)

    print_summary([pick(r, args.metric) for r in ok], args.metric, len(bad))
    print(f"copied   : {len(keep)} -> {args.outdir}")
    print(f"csv      : {report}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Score photos by sharpness. Copy each one to an output folder, renamed with the score.

The script names every copy SCORE__ORIGINALNAME.ext, and it pads the score with zeros.
A file manager then sorts the output folder from the sharpest photo to the blurriest
one. The script also writes scores.csv, which holds all four metrics for every file.

Metrics:
    laplacian   Variance of the Laplacian over the whole frame (Pech-Pacheco, 2000).
                This is the standard no-reference blur measure. A high score means
                sharp, and a low score means blurry.
    tile-max    The same variance, measured for each tile of a grid. The highest tile
                wins. Use it for wildlife, because a blurred background cannot lower
                the score of a sharp subject.
    tenengrad   Mean of the squared Sobel gradient (Tenenbaum, 1970). It reacts less
                to sensor noise. The numbers run about 50 times larger.
    brightness  Mean gray value, 0 to 255. This is a diagnostic, not a sharpness
                score. It goes into scores.csv only, never into a filename.

A score carries no absolute meaning. It moves with the camera, the lens, the subject
and the options below. Rank the files inside one set. A raw file and a JPG sit on
different scales, because the camera sharpens a JPG and leaves a raw file alone.

The script reads JPG, PNG, TIFF, BMP and WEBP through OpenCV. It reads RW2, DNG, CR2,
CR3, NEF, ARW, ORF and RAF through rawpy, when rawpy is installed.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

try:
    import rawpy
except ImportError:
    rawpy = None

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
DEFAULT_EXTS = ".jpg,.jpeg,.png,.tif,.tiff,.bmp,.webp,.rw2,.dng,.cr2,.cr3,.nef,.arw,.orf,.raf"


@dataclass
class Result:
    path: Path
    laplacian: float
    tile_max: float
    tenengrad: float
    brightness: float
    error: str = ""


def read_raw_gray(path: Path) -> np.ndarray | None:
    if rawpy is None:
        return None
    try:
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(
                half_size=True,
                no_auto_bright=True,
                use_camera_wb=True,
                output_bps=8,
                user_flip=0,
            )
    except Exception:
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def imread_unicode(path: Path) -> np.ndarray | None:
    if path.suffix.lower() in RAW_EXTS:
        return read_raw_gray(path)
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def normalize(gray: np.ndarray, long_edge: int) -> np.ndarray:
    h, w = gray.shape[:2]
    scale = long_edge / float(max(h, w))
    if scale < 1.0:
        gray = cv2.resize(
            gray,
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    return gray


def laplacian_variance(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def tile_max_variance(gray: np.ndarray, grid: int) -> float:
    h, w = gray.shape[:2]
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    best = 0.0
    for gy in range(grid):
        for gx in range(grid):
            y0, y1 = gy * h // grid, (gy + 1) * h // grid
            x0, x1 = gx * w // grid, (gx + 1) * w // grid
            tile = lap[y0:y1, x0:x1]
            if tile.size:
                best = max(best, float(tile.var()))
    return best


def tenengrad(gray: np.ndarray) -> float:
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def score_file(args: tuple[str, int, int]) -> Result:
    raw_path, long_edge, grid = args
    path = Path(raw_path)
    gray = imread_unicode(path)
    if gray is None:
        return Result(path, 0.0, 0.0, 0.0, 0.0, "unreadable")
    gray = normalize(gray, long_edge)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    return Result(
        path=path,
        laplacian=laplacian_variance(blurred),
        tile_max=tile_max_variance(blurred, grid),
        tenengrad=tenengrad(blurred),
        brightness=float(gray.mean()),
    )


def collect(indir: Path, exts: set[str], recursive: bool) -> list[Path]:
    it = indir.rglob("*") if recursive else indir.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in exts)


def pick(result: Result, metric: str) -> float:
    return {
        "laplacian": result.laplacian,
        "tile-max": result.tile_max,
        "tenengrad": result.tenengrad,
    }[metric]


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    pass


EPILOG = """\
examples:
  Score one folder and copy every file, the sharpest first:
    photo_quality.py IN OUT

  Rank birds by subject sharpness, and keep the 50 best files:
    photo_quality.py IN OUT --metric tile-max --top 50

  Score a whole library, and write scores.csv only:
    photo_quality.py IN OUT --recursive --dry-run

  Drop the worst files, after you read scores.csv:
    photo_quality.py IN OUT --min-score 36

output:
  OUT/00166.78__P1040528.JPG   the copy, renamed with the score
  OUT/scores.csv               rank, file, laplacian, tile_max, tenengrad, brightness

  The script reads the summary percentiles it prints from the whole input set.
  Use them to choose a value for --min-score.
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score photos by sharpness. Copy each one to an output folder, "
            "renamed with the score, so a file manager sorts the best first."
        ),
        epilog=EPILOG,
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "indir", type=Path, help="folder that holds the photos to score"
    )
    parser.add_argument(
        "outdir",
        type=Path,
        help="folder for the renamed copies and for scores.csv (created if missing)",
    )
    parser.add_argument(
        "--metric",
        choices=["laplacian", "tile-max", "tenengrad"],
        default="laplacian",
        help=(
            "which score goes into the copy filename. laplacian measures the whole "
            "frame. tile-max measures the sharpest tile, so a blurred background "
            "cannot lower the score of a sharp subject. tenengrad reacts less to "
            "sensor noise. scores.csv always holds all three"
        ),
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
        help=(
            "downscale the long edge of each photo to this many pixels before the "
            "measurement, so the scores compare across different image sizes. "
            "A larger value raises every score and slows the run"
        ),
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=4,
        help=(
            "grid size for tile-max. 4 gives a 4x4 grid of 16 tiles. A larger grid "
            "finds a smaller subject, but it also reacts more to noise"
        ),
    )
    parser.add_argument(
        "--ext",
        default=DEFAULT_EXTS,
        help="comma-separated list of the file extensions to read",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help=(
            "copy a file only when its score reaches this value. Read the "
            "percentiles that the script prints, then choose a value"
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="copy the N sharpest files only. Combines with --min-score",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="number of parallel processes. The default matches the CPU count",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write scores.csv and the summary, and copy no file",
    )
    opts = parser.parse_args()

    exts = {e if e.startswith(".") else "." + e for e in opts.ext.lower().split(",")}
    if not opts.indir.is_dir():
        print(f"error: input folder not found: {opts.indir}", file=sys.stderr)
        return 1

    files = collect(opts.indir, exts, opts.recursive)
    if not files:
        print(f"error: no matching images in {opts.indir}", file=sys.stderr)
        return 1

    print(f"scoring {len(files)} images ...", flush=True)
    jobs = [(str(p), opts.long_edge, opts.grid) for p in files]
    results: list[Result] = []
    with ProcessPoolExecutor(max_workers=opts.workers) as pool:
        for i, res in enumerate(pool.map(score_file, jobs, chunksize=4), 1):
            results.append(res)
            if i % 25 == 0 or i == len(files):
                print(f"  {i}/{len(files)}", flush=True)

    ok = [r for r in results if not r.error]
    bad = [r for r in results if r.error]
    ok.sort(key=lambda r: pick(r, opts.metric), reverse=True)

    opts.outdir.mkdir(parents=True, exist_ok=True)
    report = opts.outdir / "scores.csv"
    with report.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["rank", "file", "laplacian", "tile_max", "tenengrad", "brightness", "error"]
        )
        for rank, r in enumerate(ok, 1):
            writer.writerow(
                [
                    rank,
                    r.path.name,
                    f"{r.laplacian:.4f}",
                    f"{r.tile_max:.4f}",
                    f"{r.tenengrad:.4f}",
                    f"{r.brightness:.2f}",
                    "",
                ]
            )
        for r in bad:
            writer.writerow(["", r.path.name, "", "", "", "", r.error])

    selected = ok
    if opts.min_score is not None:
        selected = [r for r in selected if pick(r, opts.metric) >= opts.min_score]
    if opts.top is not None:
        selected = selected[: opts.top]

    copied = 0
    if not opts.dry_run:
        for r in selected:
            score = pick(r, opts.metric)
            name = f"{min(score, 99999.99):08.2f}__{r.path.stem}{r.path.suffix}"
            dest = opts.outdir / name
            n = 1
            while dest.exists():
                dest = opts.outdir / f"{name[:-len(r.path.suffix)]}_{n}{r.path.suffix}"
                n += 1
            shutil.copy2(r.path, dest)
            copied += 1

    scores = [pick(r, opts.metric) for r in ok]
    print()
    print(f"metric   : {opts.metric}")
    print(f"scored   : {len(ok)} ok, {len(bad)} failed")
    if scores:
        print(f"range    : {min(scores):.2f} .. {max(scores):.2f}")
        print(f"median   : {float(np.median(scores)):.2f}")
        for q in (10, 25, 50, 75, 90):
            print(f"  p{q:<3}   : {float(np.percentile(scores, q)):.2f}")
    print(f"copied   : {copied} -> {opts.outdir}")
    print(f"csv      : {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

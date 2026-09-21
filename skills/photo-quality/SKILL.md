---
name: photo-quality
description: Score photos by sharpness, then copy them renamed with the score.
---

# Photo quality filter

```bash
python scripts/photo_quality.py IN OUT --dry-run
```

`--help` documents every option. The script docstring explains the four metrics.

## Always dry run first

`--dry-run` writes `scores.csv` and prints the percentiles, and it copies no file.
A cutoff only makes sense after you see the spread of the set.

1. Dry run the folder.
2. Show the user the percentiles, and name the files at the bottom.
3. Ask the user to open the worst two files and the file at p10.
4. Set `--min-score` from what the user sees, then run the copy.

Step 3 carries the weight. The score ranks, and only the human eye sets the cutoff.

## What the score cannot tell you

**No absolute threshold exists.** Every score moves with the camera, the lens, the
subject and the `--long-edge` value. Rank inside one set. Never carry a cutoff from one
shoot to the next without a new dry run.

**A raw file and a JPG sit on different scales.** The camera sharpens a JPG and applies
a contrast curve. A raw file carries neither. One library ran 2 to 389 in JPG, and 9 to
22 in RW2 from the same camera.

**Texture inflates the score.** These metrics measure contrast at edges, not focus. A
feathered wing beats a smooth sky at the same focus. Compare inside one burst of one
subject.

**A narrow spread means a soft set.** A clean burst spreads 10 times or more between the
best file and the worst file. Near 2 times, the whole set missed focus. Say so instead
of presenting a winner.

## Metric choice

`laplacian` is the default and measures the whole frame. Recommend `--metric tile-max`
whenever the user shoots a subject against a blurred background, such as a bird on a
long lens. Tile-max scores the sharpest tile, so the bokeh cannot drag the file down.

## Before a large copy

A raw copy costs the full file size. 12 RW2 files weigh about 227 MB. Above a few GB,
ask the user first and offer `--top N`.

## Install

```bash
pip install opencv-python-headless numpy rawpy
```

`rawpy` stays optional and adds the raw formats.

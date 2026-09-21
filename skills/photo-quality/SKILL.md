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

## Neural scoring: photo_iqa.py

```bash
python scripts/photo_iqa.py IN
python scripts/photo_iqa.py IN OUT --top 4
```

`photo_quality.py` measures contrast at edges. `photo_iqa.py` adds two neural axes
from `pyiqa`, and it ranks every file on three axes at once.

| axis | metrics | what it sees |
|---|---|---|
| `tech` | `topiq_nr`, `musiq`, `niqe`, `brisque` | noise, blur, exposure, artifacts |
| `aesth` | `topiq_iaa`, `nima`, `laion_aes`, `clipiqa+` | composition and subject appeal |
| `sharp` | tile-max Laplacian at native resolution | focus on the subject |

Each axis is a z-score inside the folder. `mean` averages the three. `worst` takes
the lowest of the three, and it finds the file with no weak side. Sort with
`--rank-by`.

`mean` finds the file with the most total merit. `worst` finds the file with no
disqualifying flaw, because one strong axis cannot hide a weak one in a minimum.
Recommend `--rank-by worst` whenever the user picks one keeper.

The script prints the sharpness spread. Below 2x, say the set missed focus as a
whole instead of naming a winner.

Three traps this script does not remove:

1. An aesthetic model can rank a soft frame first. It scores the scene, not the
   focus. Always read the `sharp` column next to the `aesth` column.
2. A burst of one scene gives a tiny aesthetic spread. Every frame shows the same
   composition, so `aesth` separates almost nothing. Weight `tech` and `sharp`
   higher for a burst.
3. `tech` reads the whole frame, so smooth bokeh lowers it. A subject against a
   blurred background scores lower than a flat textured wall at the same focus.
   That is the reason `sharp` reads one tile only.

The raw and JPG warning above applies to every model here. All eight learned on
finished JPG, so a raw file scores lower on all of them. Compare inside one format.

Install:

```bash
pip install torch torchvision pyiqa opencv-python rawpy
```

The first run downloads about 600 MB of model weights into `~/.cache/torch/hub/pyiqa`.
The script carries a shim for `pkg_resources`, which Python 3.14 and setuptools 81
removed, and which `openai-clip` still imports.

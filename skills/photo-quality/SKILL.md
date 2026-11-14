---
name: photo-quality
description: Rank a folder of photos by sharpness, or by neural image quality assessment, then copy the best.
disable-model-invocation: true
---

# Photo quality

Two scripts rank the photos of one folder. `--help` documents every option and metric.

| script | method | ranks by |
|---|---|---|
| `photo_sharpness.py` | classic sharpness metrics, contrast at edges | sharpness only |
| `photo_iqa.py` | neural image quality assessment (IQA) with `pyiqa` | technical quality, aesthetics and sharpness |

## Install

`photo_sharpness.py`:

```bash
pip install opencv-python-headless numpy rawpy
```

`photo_iqa.py`:

```bash
pip install torch torchvision pyiqa opencv-python rawpy
```

The first `photo_iqa.py` run downloads about 2.6 GB of model weights into `~/.cache`
(`torch/hub`, `clip` and `huggingface`). The script carries a shim for
`pkg_resources`, which setuptools no longer ships, and which `openai-clip` still
imports.

## photo_sharpness.py

```bash
python scripts/photo_sharpness.py IN OUT --dry-run
```

Always dry run first. `--dry-run` writes `scores.csv`, prints the percentiles, and
copies no file. A cutoff only makes sense after you see the spread of the set.

1. Dry run the folder.
2. Show the user the percentiles, and name the files at the bottom.
3. Ask the user to open the worst two files and the file at p10.
4. Set `--min-score` from what the user sees, then run the copy.

Step 3 carries the weight. The score ranks, and only the human eye sets the cutoff.

`laplacian` is the default metric and measures the whole frame. Recommend
`--metric tile-max` when the subject stands against a blurred background, such as a
bird on a long lens. Tile-max scores the sharpest tile, so the bokeh cannot drag the
file down.

A copy costs the full file size. 12 RW2 files weigh about 227 MB. Above a few GB, ask
the user first and offer `--top N`.

## photo_iqa.py

```bash
python scripts/photo_iqa.py IN
python scripts/photo_iqa.py IN OUT --top 4
```

Without `OUT`, the script writes its CSV into `IN` and copies no file.

`photo_sharpness.py` measures contrast at edges only. `photo_iqa.py` adds two
neural axes, and it ranks every file on three axes at once.

| axis | metrics | what it sees |
|---|---|---|
| `tech` | `topiq_nr`, `musiq`, `niqe`, `brisque` | noise, blur, exposure, artifacts |
| `aesth` | `topiq_iaa`, `nima`, `laion_aes`, `clipiqa+` | composition and subject appeal |
| `sharp` | tile-max Laplacian at native resolution | focus on the subject |

Each axis is a z-score inside the folder. Sort with `--rank-by`:

- `mean` averages the three axes. It finds the file with the most total merit.
- `worst` takes the lowest axis. It finds the file with no disqualifying flaw,
  because one strong axis cannot hide a weak one in a minimum. Recommend it whenever
  the user picks one keeper.

Three traps the script does not remove:

1. An aesthetic model can rank a soft frame first. It scores the scene, not the
   focus. Always read the `sharp` column next to the `aesth` column.
2. A burst of one scene gives a tiny aesthetic spread. Every frame shows the same
   composition, so `aesth` separates almost nothing. Weight `tech` and `sharp`
   higher for a burst.
3. `tech` reads the whole frame, so smooth bokeh lowers it. A subject against a
   blurred background scores lower than a flat textured wall at the same focus.
   That is the reason `sharp` reads one tile only.

## Limits of every score

These apply to both scripts.

**No absolute threshold exists.** The scores move with the camera, the lens, the
subject and the `--long-edge` value. Rank inside one set. Never carry a cutoff from one
shoot to the next without a new run.

**A raw file and a JPG sit on different scales.** The camera sharpens a JPG and applies
a contrast curve. A raw file carries neither. One library ran 2 to 389 in JPG, and 9 to
22 in RW2 from the same camera. All eight pyiqa metrics learned on finished JPG, so a
raw file scores lower on all of them. Compare inside one format.

**Texture inflates sharpness.** The sharpness metrics measure contrast at edges, not
focus. A feathered wing beats a smooth sky at the same focus. Compare inside one burst
of one subject.

**A narrow spread means a soft set.** In `photo_sharpness.py`, a clean burst spreads
10 times or more between the best file and the worst file, and near 2 times the whole
set missed focus. `photo_iqa.py` prints its sharpness spread, and below 2 times the set
missed focus. Say so instead of presenting a winner.

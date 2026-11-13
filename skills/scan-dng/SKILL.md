---
name: scan-dng
description: Wrap a film scan (JPEG, PNG, ...) in a raw DNG that poses as a Panasonic DMC-G7, so DxO PureRAW accepts it.
disable-model-invocation: true
---

# Scan to DNG for DxO PureRAW

```bash
python scripts/jpg2dng.py SCAN OUT.dng
```

`--help` documents every option. The script refuses to overwrite `OUT.dng`.

DxO PureRAW opens camera raw files only. The script upscales the scan 3 times, converts
it to G7 camera colour, mosaics it into a Bayer pattern, and writes a 16-bit DNG. It
then decodes the file with rawpy and stops on any mismatch.

For a folder, loop in the shell. Write each DNG next to its scan with the same name.

## What the user sees

**DxO output is 0.7 times as bright as the scan.** Tell the user to add +0.5 EV in the
editor, or to use Smart Lighting. DxO ignores `BaselineExposure`, so the file cannot
carry this correction.

**DxO output size equals the size the script prints.** The DNG is larger, because it
holds black padding that DxO crops away. Check the DxO output against the printed size.

**Windows Photos shows a thin black border and a 216 px black strip on the right.**
Windows ignores `DefaultCrop`. This is correct. DxO removes both.

**A viewer shows more contrast than the scan.** The viewer applies its own tone curve
to a raw file. The data in the file matches the scan.

**Portrait scans work.** DxO crops the raw buffer before it rotates. The script applies
the EXIF orientation of the scan before it builds the file.

## Do not change these values

Each one came from a DxO test. A change breaks the DxO output.

| value | reason |
|---|---|
| `CAM_XYZ`, `CFA` | DxO uses its own G7 calibration. A neutral matrix gave oversaturated colour. |
| `HEADROOM = 0.7` | DxO clips above about 0.743 of the range. Smart Lighting then makes white specks. |
| `PAD_*` = 8, 8, 8, 216 | DxO always crops the G7 sensor margins and ignores `DefaultCrop`. |
| raw data in IFD0 | The Windows DNG decoder reads IFD0 only. |
| `SCALE = 3` | 3 times cuts colour fringes by half against 2 times. 4 times adds little. |
| Lanczos | It gives half the colour error of `--nearest` after demosaic. |

## Failed approaches

Do not try these again:

1. A linear DNG (`LinearRaw`). DxO rejects it.
2. A flat `ProfileToneCurve`. Windows ignores it.
3. `BaselineExposure`. DxO ignores it in the render and in its output DNG.
4. A fake RW2. LibRaw reads only part of the border tags, and DxO ignores the crop tags.

## Before a large batch

Each DNG weighs about 42 MB for a 1818x1228 scan. A roll of 36 scans weighs about
1.5 GB. Above a few GB, ask the user first.

## Install

```bash
pip install numpy rawpy Pillow
```

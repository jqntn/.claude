---
name: scan-dng
description: Wrap a film scan (JPEG, PNG, ...) in a raw DNG that poses as a Panasonic DMC-G7, so DxO PureRAW accepts it.
disable-model-invocation: true
---

# Scan to DNG for DxO PureRAW

```bash
python scripts/jpg2dng.py SCAN OUT.dng
```

For a folder, loop in the shell and write each DNG next to its scan with the same name.

Tell the user:

- DxO output is 0.7 times as bright as the scan. Add +0.5 EV in the editor to restore it.
- Windows Photos shows a black border and a black strip on the right. DxO crops both.

## Install

```bash
pip install numpy rawpy Pillow
```

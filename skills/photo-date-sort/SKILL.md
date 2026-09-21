---
name: photo-date-sort
description: Sort .RW2 photos into dated folders by EXIF date.
---

# Photo date sort

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Sort-Rw2.ps1 -In "D:\DCIM" -Out "C:\Pictures\LUMIX" -DryRun
```

The tree, exactly:

```
OUT/2026.08.01/RAW-2026.08.01/P1040426.RW2
```

## Always dry run first

`-DryRun` prints the plan and a date histogram, and it changes nothing. Show the user the
histogram before the copy. A card often holds two shoots, and the user expects one.

Drop `-DryRun` to copy. Offer `-Move` only after a clean copy, and only to clear a card.

## The date comes from the EXIF metadata

Never from the file timestamp. A copy or a restore rewrites a timestamp, and every file
then lands on one wrong day.

A file already at the target, with the same name and the same size, is skipped, so a rerun
is free.

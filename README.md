# .claude

My Claude Code configuration.

## Install

```sh
git clone https://github.com/jqntn/.claude.git ~/.claude
```

## Prerequisites

| Command | Needed by | How to install |
| --- | --- | --- |
| `python3` | The 4 hooks in `skills/asd-ste100/hooks/hooks.json` | Microsoft Store Python, or python.org plus a `python3` alias |
| `ccstatusline` | The `statusLine` command in `settings.json` | `npm i -g ccstatusline` |

## Contents

- `CLAUDE.md`: global instructions for all projects.

- `settings.json`: permissions, plugins, theme, and the status line command.

- `ccstatusline-config.json`: an export of the status line layout.

- `hooks/caveman-statusline.ps1`: the caveman badge script.

- `skills/asd-ste100/`: a vendored writing skill.

The `.gitignore` denies everything, then allows the files above. Credentials,
history, transcripts, caches, and sessions stay out of the repo.

## Status line

The status line uses [ccstatusline](https://github.com/sirmalloc/ccstatusline).
Its live config lives at `~/.config/ccstatusline/settings.json`, outside this
repo. `ccstatusline-config.json` is an export of that file.

To restore the layout, run `ccstatusline`, then choose **Import Config**, then
select `~/.claude/ccstatusline-config.json`.

After a change to the layout, export the config again, and copy it over
`ccstatusline-config.json`. The 2 files do not sync on their own.

## Notes

`skills/asd-ste100` comes from a third-party project, and it keeps its own
`LICENSE`. Upstream: https://github.com/woosal1337/blog

`hooks/caveman-statusline.ps1` is a copy of the script the caveman plugin
ships. Upstream: https://github.com/JuliusBrussee/caveman

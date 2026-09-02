$ErrorActionPreference = 'SilentlyContinue'

$cfg = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.claude' }
$glob = Join-Path $cfg 'plugins\cache\caveman\caveman\*\src\hooks\caveman-statusline.ps1'
$script = Get-ChildItem -Path $glob -File | Sort-Object LastWriteTime | Select-Object -Last 1

if ($script) { & $script.FullName }

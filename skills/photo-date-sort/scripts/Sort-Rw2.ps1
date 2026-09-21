[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$In,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$Out,

    [switch]$Move,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-U16($b, $i, $le) {
    if ($le) { return ([int]$b[$i]) -bor (([int]$b[$i + 1]) -shl 8) }
    return (([int]$b[$i]) -shl 8) -bor ([int]$b[$i + 1])
}

function Get-U32($b, $i, $le) {
    if ($le) {
        return ([int64]$b[$i]) -bor (([int64]$b[$i + 1]) -shl 8) -bor (([int64]$b[$i + 2]) -shl 16) -bor (([int64]$b[$i + 3]) -shl 24)
    }
    return (([int64]$b[$i]) -shl 24) -bor (([int64]$b[$i + 1]) -shl 16) -bor (([int64]$b[$i + 2]) -shl 8) -bor ([int64]$b[$i + 3])
}

function Get-Rw2Date([string]$Path) {
    $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $len = $fs.Length

        $rd = {
            param($off, $n)
            if ($off -lt 0 -or $n -le 0 -or ($off + $n) -gt $len) { throw 'offset out of range' }
            $buf = New-Object byte[] $n
            $fs.Position = $off
            $got = 0
            while ($got -lt $n) {
                $r = $fs.Read($buf, $got, $n - $got)
                if ($r -le 0) { throw 'short read' }
                $got += $r
            }
            return , $buf
        }

        $h = & $rd 0 8
        if ($h[0] -eq 0x49 -and $h[1] -eq 0x49) { $le = $true }
        elseif ($h[0] -eq 0x4D -and $h[1] -eq 0x4D) { $le = $false }
        else { return $null }

        $magic = Get-U16 $h 2 $le
        if ($magic -ne 0x55 -and $magic -ne 0x2A) { return $null }

        $readIfd = {
            param($off)
            $cb = & $rd $off 2
            $n = Get-U16 $cb 0 $le
            if ($n -le 0 -or $n -gt 1024) { return @{} }
            $eb = & $rd ($off + 2) ($n * 12)
            $map = @{}
            for ($i = 0; $i -lt $n; $i++) {
                $p = $i * 12
                $map[(Get-U16 $eb $p $le)] = @{
                    Type  = Get-U16 $eb ($p + 2) $le
                    Count = Get-U32 $eb ($p + 4) $le
                    Off   = Get-U32 $eb ($p + 8) $le
                    Raw   = $eb[($p + 8)..($p + 11)]
                }
            }
            return $map
        }

        $readAscii = {
            param($e)
            if ($null -eq $e -or $e.Type -ne 2) { return $null }
            $c = [int]$e.Count
            if ($c -le 0 -or $c -gt 4096) { return $null }
            if ($c -le 4) { $b = $e.Raw } else { $b = & $rd $e.Off $c }
            $s = [System.Text.Encoding]::ASCII.GetString($b, 0, [Math]::Min($c, $b.Length))
            return $s.Split([char]0)[0].Trim()
        }

        $ifd0 = & $readIfd (Get-U32 $h 4 $le)

        $raw = $null
        if ($ifd0.ContainsKey(0x8769)) {
            $exif = & $readIfd ([int64]$ifd0[0x8769].Off)
            foreach ($tag in 0x9003, 0x9004) {
                if ($exif.ContainsKey($tag)) {
                    $v = & $readAscii $exif[$tag]
                    if ($v) { $raw = $v; break }
                }
            }
        }
        if (-not $raw -and $ifd0.ContainsKey(0x0132)) { $raw = & $readAscii $ifd0[0x0132] }
        if (-not $raw) { return $null }

        $m = [regex]::Match($raw, '^(\d{4})[:\-](\d{2})[:\-](\d{2})')
        if (-not $m.Success) { return $null }
        if ($m.Groups[1].Value -eq '0000' -or $m.Groups[2].Value -eq '00' -or $m.Groups[3].Value -eq '00') { return $null }
        return '{0}.{1}.{2}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value
    }
    finally {
        $fs.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $In -PathType Container)) {
    [Console]::Error.WriteLine('ERROR: the IN directory does not exist: "' + $In + '"')
    exit 2
}

$src = (Resolve-Path -LiteralPath $In).ProviderPath

if ($DryRun) {
    $dst = [System.IO.Path]::GetFullPath($Out)
}
else {
    try {
        if (-not (Test-Path -LiteralPath $Out -PathType Container)) {
            New-Item -ItemType Directory -Path $Out -Force | Out-Null
        }
        $dst = (Resolve-Path -LiteralPath $Out).ProviderPath
    }
    catch {
        [Console]::Error.WriteLine('ERROR: the program cannot create the OUT directory: "' + $Out + '"')
        exit 2
    }
}

$verb = if ($Move) { 'MOVE' } else { 'COPY' }
$mode = if ($DryRun) { " [dry run, nothing changes]" } else { '' }

$files = @(Get-ChildItem -LiteralPath $src -Recurse -File -Filter '*.RW2' | Sort-Object FullName)
if ($files.Count -eq 0) {
    Write-Host "No .RW2 file found in `"$src`"."
    exit 0
}

Write-Host ("Found {0} .RW2 file(s) in `"{1}`".{2}" -f $files.Count, $src, $mode)
Write-Host ''

$done = 0
$present = 0
$dates = @{}
$problems = New-Object System.Collections.Generic.List[string]

foreach ($f in $files) {
    $date = $null
    try { $date = Get-Rw2Date $f.FullName }
    catch {
        $problems.Add(("{0} -- the program cannot read the metadata: {1}" -f $f.FullName, $_.Exception.Message))
        continue
    }

    if (-not $date) {
        $problems.Add(("{0} -- the file holds no capture date" -f $f.FullName))
        continue
    }

    $leaf = "RAW-$date"
    $dir = Join-Path (Join-Path $dst $date) $leaf
    $target = Join-Path $dir $f.Name
    $dates[$date] = 1 + $(if ($dates.ContainsKey($date)) { $dates[$date] } else { 0 })

    if (-not $DryRun -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    if (Test-Path -LiteralPath $target) {
        if ((Get-Item -LiteralPath $target).Length -eq $f.Length) {
            $present++
            Write-Host ("SKIP  {0} -> {1}\{2} (already there)" -f $f.Name, $date, $leaf)
            if ($Move -and -not $DryRun) { Remove-Item -LiteralPath $f.FullName -Force }
        }
        else {
            $problems.Add(("{0} -- a different file with this name is already in `"{1}`"" -f $f.FullName, $dir))
        }
        continue
    }

    if (-not $DryRun) {
        if ($Move) { Move-Item -LiteralPath $f.FullName -Destination $target }
        else { Copy-Item -LiteralPath $f.FullName -Destination $target -Force }
    }

    $done++
    Write-Host ("{0}  {1} -> {2}\{3}" -f $verb, $f.Name, $date, $leaf)
}

Write-Host ''
if ($dates.Count -gt 0) {
    Write-Host ("Dates: {0}" -f (($dates.Keys | Sort-Object | ForEach-Object { "$_ ($($dates[$_]))" }) -join '  '))
}
$label = if ($DryRun) { "Planned $verb" } else { "${verb}D" }
Write-Host ("{0}: {1}   Already there: {2}   Problems: {3}" -f $label, $done, $present, $problems.Count)

if ($problems.Count -gt 0) {
    Write-Host ''
    Write-Host 'Problems:'
    foreach ($p in $problems) { Write-Host ("  " + $p) }
    exit 1
}

exit 0

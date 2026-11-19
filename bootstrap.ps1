param([string]$PythonVersion = '3.13.17', [string]$PySideVersion = '6.12.0', [string]$PythonSHA256)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
if ($PythonVersion -notmatch '^\d+\.\d+\.\d+$' -or $PySideVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid dependency version.' }
if (-not $PythonSHA256 -and $PythonVersion -eq '3.13.17') { $PythonSHA256 = '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38' }
if ($PythonSHA256 -notmatch '^[0-9a-f]{64}$') { throw 'Supply the official Windows embedded archive SHA256.' }
$cache = Join-Path $root 'downloads'
$work = Join-Path $root ('_bootstrap-' + [guid]::NewGuid())
$runtime = Join-Path $work 'runtime'
New-Item -ItemType Directory -Force $cache | Out-Null
New-Item -ItemType Directory -Path $work | Out-Null
$short = ($PythonVersion.Split('.')[0..1] -join '')
$filename = "python-$PythonVersion-embed-amd64.zip"
$archive = Join-Path $cache $filename
if (-not (Test-Path $archive) -or (Get-FileHash $archive).Hash -ne $PythonSHA256) {
    $pending = Join-Path $work $filename
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/$filename" -OutFile $pending -UseBasicParsing
    if ((Get-FileHash $pending).Hash -ne $PythonSHA256) { throw 'CPython archive checksum mismatch.' }
    Copy-Item -LiteralPath $pending -Destination $archive -Force
}
Expand-Archive -LiteralPath $archive -DestinationPath $runtime
$signature = Get-AuthenticodeSignature (Join-Path $runtime "python$short.dll")
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') { throw 'CPython signature verification failed.' }
Set-Content (Join-Path $runtime "python$short._pth") -Encoding ASCII -Value @("python$short.zip",'.','Lib\site-packages','..','import site')
New-Item -ItemType Directory -Force (Join-Path $runtime 'Lib\site-packages') | Out-Null
& (Join-Path $runtime 'python.exe') -B (Join-Path $root 'tools\prepare_dependencies.py') $work $PySideVersion
if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed, working installation preserved. Staging: $work" }

# Only the two explicitly named development directories are exchanged. Keep
# complete prior versions until both new directories are in place.
$moved = @()
$installed = @()
try {
    foreach ($name in @('runtime','bundle')) {
        $dest = Join-Path $root $name
        if (Test-Path $dest) {
            if ((Get-Item -LiteralPath $dest).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing reparse point: $dest" }
            Move-Item -LiteralPath $dest -Destination (Join-Path $work "old-$name")
            $moved += $name
        }
        Move-Item -LiteralPath (Join-Path $work $name) -Destination $dest
        $installed += $name
    }
} catch {
    foreach ($name in $installed) { Move-Item -LiteralPath (Join-Path $root $name) -Destination (Join-Path $work $name) }
    foreach ($name in $moved) { Move-Item -LiteralPath (Join-Path $work "old-$name") -Destination (Join-Path $root $name) }
    throw
}
$resolved = (Resolve-Path -LiteralPath $work).Path
if ([IO.Path]::GetDirectoryName($resolved) -ne $root -or [IO.Path]::GetFileName($resolved) -notmatch '^_bootstrap-[0-9a-f-]{36}$') { throw 'Unexpected staging path.' }
Remove-Item -LiteralPath $resolved -Recurse -Force
Write-Host 'Verified portable dependencies and engine are ready.'

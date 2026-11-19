param([switch]$KeepExistingData, [switch]$Release)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$dist = Join-Path $root 'dist'
$archive = 'byerkn-portable.zip'
if ($Release) {
    $version = & (Join-Path $root 'runtime\python.exe') -B -c "from byerkn import __version__; print(__version__)"
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version.' }
    $dist = Join-Path $dist "release-$version"
    $archive = "byerkn-$version-windows-x64.zip"
}
$work = Join-Path $dist ('_build-' + [guid]::NewGuid())
$stage = Join-Path $work 'byerkn'

function Step([string]$text) { Write-Host $text -ForegroundColor Cyan }
function Check([bool]$ok, [string]$message) { if (-not $ok) { throw $message } }

Step '1/6  Checking source components'
foreach ($path in @('runtime\pythonw.exe','runtime\Lib\site-packages\PySide6','bundle\bin\winws.exe','bundle\general.bat','assets\icon.ico','assets\fonts\GolosText-VF.ttf','assets\fonts\InstrumentSerif-Italic.ttf')) {
    Check (Test-Path (Join-Path $root $path)) "Missing $path. Run bootstrap.ps1 first."
}

Step '2/6  Preparing a clean portable directory'
if (Test-Path $work) { throw 'Staging directory already exists.' }
New-Item -ItemType Directory -Force $stage | Out-Null
foreach ($name in @('byerkn','runtime','bundle','assets','licenses','launcher','docs')) {
    Copy-Item -LiteralPath (Join-Path $root $name) -Destination $stage -Recurse
}
foreach ($name in @('README.md','README.ru.md','LICENSE','THIRD_PARTY.md')) {
    Copy-Item -LiteralPath (Join-Path $root $name) -Destination $stage
}
Copy-Item -LiteralPath (Join-Path $root 'portable-readme.txt') -Destination (Join-Path $stage 'Readme.txt')
foreach ($cache in @(Get-ChildItem -LiteralPath $stage -Recurse -Directory -Filter '__pycache__')) {
    if (-not $cache.FullName.StartsWith($stage + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected cache path' }
    Remove-Item -LiteralPath $cache.FullName -Recurse -Force
}

Step '3/6  Compiling byerkn.exe with the administrator manifest'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
Check (Test-Path $csc) 'The system C# compiler was not found.'
& $csc /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 `
    /reference:System.Windows.Forms.dll `
    "/win32icon:$(Join-Path $root 'assets\icon.ico')" `
    "/win32manifest:$(Join-Path $root 'launcher\app.manifest')" `
    "/out:$(Join-Path $stage 'byerkn.exe')" `
    (Join-Path $root 'launcher\Launcher.cs')
Check ($LASTEXITCODE -eq 0) 'byerkn.exe compilation failed.'

Step '4/6  Verifying the staged runtime and real interface'
$oldRoot = $env:BYERKN_TEST_ROOT
try {
    $env:BYERKN_TEST_ROOT = $stage
    & (Join-Path $stage 'runtime\python.exe') -B (Join-Path $root 'tests\capture_ui.py')
    Check ($LASTEXITCODE -eq 0) 'Staged interface check failed.'
} finally {
    $env:BYERKN_TEST_ROOT = $oldRoot
}

Step '5/6  Packaging and comparing every archived file'
& (Join-Path $root 'runtime\python.exe') -B (Join-Path $root 'tools\package_portable.py') $stage $archive
Check ($LASTEXITCODE -eq 0) "Publishing failed; staging retained in $work"
if ($Release) {
    $zip = Join-Path $dist $archive
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$zip.sha256" -Encoding ASCII -Value "$hash  $archive"
}

Step '6/6  Cleaning the completed build'
$resolved = (Resolve-Path -LiteralPath $work).Path
if ([IO.Path]::GetDirectoryName($resolved) -ne (Resolve-Path -LiteralPath $dist).Path -or
    [IO.Path]::GetFileName($resolved) -notmatch '^_build-[0-9a-f-]{36}$') { throw 'Unexpected staging path.' }
Remove-Item -LiteralPath $resolved -Recurse -Force

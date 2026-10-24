# Use a project-local interpreter and deterministic UTF-8 for inherited upstream I/O.
$ErrorActionPreference = 'Stop'
$rememRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$rememPython = Join-Path $rememRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $rememPython)) { throw 'Create the project .venv first.' }
$previousUtf8 = $env:PYTHONUTF8
$previousEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    & $rememPython -X utf8 @args
    $rememExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONUTF8 = $previousUtf8
    $env:PYTHONIOENCODING = $previousEncoding
}
exit $rememExitCode

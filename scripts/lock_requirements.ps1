# Regenerate the hash-locked requirements files that CI installs with --require-hashes.
# Run after changing requirements.txt, requirements-dev.txt or .github/requirements/ci-tools.in.
# Needs uv: python -m pip install uv
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$common = @('pip', 'compile', '--universal', '--python-version', '3.11', '--generate-hashes', '--quiet')
uv @common requirements.txt -o requirements.lock
uv @common requirements-dev.txt -o requirements-dev.lock
uv @common .github/requirements/ci-tools.in -o .github/requirements/ci-tools.lock

python scripts/check_locks.py

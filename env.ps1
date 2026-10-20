# Keeps everything (Python, packages, caches, models) inside this folder.
# Usage:  . .\env.ps1            -> set env vars for this shell
#         . .\env.ps1 -Setup     -> also create/update the venv
param([switch]$Setup)

$root = $PSScriptRoot
$env:UV_PYTHON_INSTALL_DIR = "$root\.tools\python"
$env:UV_CACHE_DIR          = "$root\.tools\uv-cache"
$env:UV_PROJECT_ENVIRONMENT = "$root\.venv"
$env:HF_HOME               = "$root\models\hf"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

if ($Setup) {
    uv python install 3.12
    uv sync --python 3.12 --managed-python
}

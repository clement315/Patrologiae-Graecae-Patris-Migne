# =====================================================================
#  PG OCR - environment setup (step 1: data + layout, no recognition yet)
#
#  Run in PowerShell:
#     powershell -ExecutionPolicy Bypass -File .\setup_pg_ocr.ps1
#  Optional other target folder:
#     powershell -ExecutionPolicy Bypass -File .\setup_pg_ocr.ps1 -Root "D:\PG_OCR"
#  Small CPU-only PyTorch (~200 MB instead of ~3 GB), enough for data prep
#  and layout detection:
#     powershell -ExecutionPolicy Bypass -File .\setup_pg_ocr.ps1 -CpuTorch
#
#  Everything (Python, packages, caches, data) goes under $Root.
#  Nothing is installed on C:, no system settings or PATH are changed.
#  Safe to re-run: finished steps are skipped.
# =====================================================================
param([string]$Root = "E:\PG_OCR", [switch]$CpuTorch)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "FAILED: $what (exit code $LASTEXITCODE)" } }

# ---------------------------------------------------------------------
Step "1/6  Create folders under $Root"
$dirs = @("tools", "cache", "models", "scripts", "output", "work",
          "data\pdf", "data\pages", "data\zenodo\downloads")
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null }

# Keep every cache off drive C:
$env:UV_INSTALL_DIR        = "$Root\tools\uv"
$env:UV_NO_MODIFY_PATH     = "1"
$env:UV_CACHE_DIR          = "$Root\cache\uv"
$env:UV_PYTHON_INSTALL_DIR = "$Root\tools\python"
$env:UV_LINK_MODE          = "copy"
$env:PIP_CACHE_DIR         = "$Root\cache\pip"
$env:TORCH_HOME            = "$Root\cache\torch"
$env:YOLO_CONFIG_DIR       = "$Root\cache\ultralytics"
$env:HF_HOME               = "$Root\cache\hf"
$env:PG_ROOT               = $Root

# ---------------------------------------------------------------------
Step "2/6  Install uv (Python package manager) into $Root\tools\uv"
$uv = "$Root\tools\uv\uv.exe"
if (-not (Test-Path $uv)) {
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    Check "uv install"
}
if (-not (Test-Path $uv)) { throw "uv.exe not found at $uv" }
& $uv --version

# ---------------------------------------------------------------------
Step "3/6  Create Python 3.11 virtual environment in $Root\.venv"
$py = "$Root\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    & $uv venv "$Root\.venv" --python 3.11 --python-preference only-managed
    Check "create venv"
}
& $py --version

# ---------------------------------------------------------------------
if ($CpuTorch) {
    Step "4/6  Install PyTorch (CPU-only build, ~200 MB) and tools"
    $torchIndex = "https://download.pytorch.org/whl/cpu"
} else {
    Step "4/6  Install PyTorch (CUDA 12.8 build, ~3 GB) and tools"
    $torchIndex = "https://download.pytorch.org/whl/cu128"
}
& $uv pip install --python $py torch torchvision --index-url $torchIndex
Check "install torch"
# ultralytics : YOLO (layout model + later line detection)
# lxml        : PageXML parsing
# pymupdf     : PDF -> page images (no poppler needed on Windows)
# shapely     : polygon geometry (regions / lines)
& $uv pip install --python $py ultralytics lxml pymupdf shapely pandas tqdm jupyterlab
Check "install packages"

# ---------------------------------------------------------------------
Step "5/6  Download Calfa ground truth (Zenodo, ~526 MB) and layout model"
function Get-Verified($url, $dest, $md5) {
    if ((Test-Path $dest) -and $md5 -and ((Get-FileHash $dest -Algorithm MD5).Hash -eq $md5.ToUpper())) {
        Write-Host "  already downloaded: $(Split-Path $dest -Leaf)"; return
    }
    Write-Host "  downloading $(Split-Path $dest -Leaf) ..."
    curl.exe -L --fail --retry 3 -o $dest $url
    Check "download $url"
    if ($md5) {
        $h = (Get-FileHash $dest -Algorithm MD5).Hash
        if ($h -ne $md5.ToUpper()) { throw "MD5 mismatch for $dest (got $h)" }
        Write-Host "  MD5 OK"
    }
}
$dl = "$Root\data\zenodo\downloads"
Get-Verified "https://zenodo.org/records/20008699/files/data.zip?download=1"    "$dl\data.zip"    "308fc796f4290afa51d5c7814ab4a0f5"
Get-Verified "https://zenodo.org/records/20008699/files/data-v2.zip?download=1" "$dl\data-v2.zip" "20bf8621dfb4dfe4d9270eee26cfc90e"

foreach ($pair in @(@("data.zip", "v1"), @("data-v2.zip", "v2"))) {
    $target = "$Root\data\zenodo\$($pair[1])"
    if (-not (Test-Path $target)) {
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        Write-Host "  extracting $($pair[0]) -> $target"
        tar.exe -xf "$dl\$($pair[0])" -C $target
        Check "extract $($pair[0])"
    }
}

$model = "$Root\models\REG-YOLOv12s.pt"
if (-not (Test-Path $model)) {
    Write-Host "  downloading layout model REG-YOLOv12s.pt (GitHub calfa-co/Patrologia-Graeca)"
    curl.exe -L --fail --retry 3 -o $model "https://github.com/calfa-co/Patrologia-Graeca/raw/main/models/REG-YOLOv12s.pt"
    Check "download layout model"
}

# ---------------------------------------------------------------------
Step "6/6  Write start scripts and run environment check"

# start.ps1: sets the cache folders and activates the venv (no permanent changes)
$start = @'
$Root = "__ROOT__"
$env:UV_CACHE_DIR          = "$Root\cache\uv"
$env:UV_PYTHON_INSTALL_DIR = "$Root\tools\python"
$env:UV_LINK_MODE          = "copy"
$env:PIP_CACHE_DIR         = "$Root\cache\pip"
$env:TORCH_HOME            = "$Root\cache\torch"
$env:YOLO_CONFIG_DIR       = "$Root\cache\ultralytics"
$env:HF_HOME               = "$Root\cache\hf"
$env:PG_ROOT               = $Root
$env:PATH                  = "$Root\tools\uv;$env:PATH"
. "$Root\.venv\Scripts\Activate.ps1"
Set-Location $Root
Write-Host "PG OCR environment ready ($Root). Python: $(python --version)" -ForegroundColor Green
'@ -replace "__ROOT__", $Root
Set-Content -Path "$Root\start.ps1" -Value $start -Encoding ASCII

# start.bat: double-click to open a ready PowerShell window
Set-Content -Path "$Root\start.bat" -Encoding ASCII -Value `
    "@echo off`r`npowershell -NoExit -ExecutionPolicy Bypass -File `"%~dp0start.ps1`""

$check = @'
"""PG OCR environment check: GPU, packages, layout model, Zenodo data."""
import glob
import os
import sys
from collections import Counter

ROOT = os.environ.get("PG_ROOT", r"E:\PG_OCR")
print("Python      :", sys.version.split()[0])

import torch
print("PyTorch     :", torch.__version__, "| CUDA build", torch.version.cuda)
cuda = torch.cuda.is_available()
print("CUDA usable :", cuda)
if cuda:
    p = torch.cuda.get_device_properties(0)
    print("GPU         : %s, %.1f GB" % (p.name, p.total_memory / 1024 ** 3))
    x = torch.randn(2048, 2048, device="cuda")
    (x @ x).sum().item()
    print("GPU test    : matrix multiply OK")
else:
    print("Note: running on CPU (expected with -CpuTorch; fine for data prep and layout)")

import fitz
import lxml
import shapely
import ultralytics
print("ultralytics :", ultralytics.__version__)
print("PyMuPDF     :", getattr(fitz, "VersionBind", "?"), "| shapely", shapely.__version__)

zroot = os.path.join(ROOT, "data", "zenodo")
imgs = sorted(p for ext in ("jpg", "jpeg", "png", "tif", "tiff")
              for p in glob.glob(os.path.join(zroot, "v*", "**", "*." + ext), recursive=True))
xmls = glob.glob(os.path.join(zroot, "v*", "**", "*.xml"), recursive=True)
print("Zenodo data : %d images, %d XML files" % (len(imgs), len(xmls)))

from ultralytics import YOLO
model = YOLO(os.path.join(ROOT, "models", "REG-YOLOv12s.pt"))
print("Layout model classes:", model.names)

if imgs:
    res = model.predict(imgs[0], device=0 if cuda else "cpu", conf=0.25, verbose=False)[0]
    out = os.path.join(ROOT, "output", "layout_test.jpg")
    res.save(filename=out)
    counts = Counter(model.names[int(c)] for c in res.boxes.cls)
    print("Test page   :", os.path.relpath(imgs[0], zroot))
    print("Regions     :", dict(counts))
    print("Saved       :", out)

print("\nALL CHECKS DONE")
'@
Set-Content -Path "$Root\scripts\check_env.py" -Value $check -Encoding ASCII

& $py "$Root\scripts\check_env.py"
Check "environment check"

Write-Host "`nSetup finished." -ForegroundColor Green
Write-Host "Next time: double-click $Root\start.bat to open a ready terminal."
Write-Host "Layout test image: $Root\output\layout_test.jpg"

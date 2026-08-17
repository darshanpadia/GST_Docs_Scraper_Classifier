# One-shot local setup for Windows: creates a venv, installs the project
# (including dev deps for running tests), and prints next steps.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -e ".[dev,llm]"

Write-Host ""
Write-Host "Setup complete."
Write-Host "If 'gst-agent' isn't recognized in this or a new terminal, activate"
Write-Host "the venv explicitly first:"
Write-Host ""
Write-Host "    .venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Then:"
Write-Host "    gst-agent --once"
Write-Host "    gst-agent --stats"
Write-Host ""
Write-Host "Note: OCR needs the Tesseract system binary installed separately --"
Write-Host "see README.md 'OCR setup' if you plan to process scanned PDFs."

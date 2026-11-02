#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" -m PyInstaller --noconfirm --clean --onedir --windowed --name CodexBridge --paths src \
  --copy-metadata keyring --collect-submodules keyring.backends --hidden-import keyring.backends.macOS \
  --exclude-module keyring.testing --exclude-module pytest \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.QtPdf scripts/desktop_entry.py
"$PYTHON" scripts/collect_licenses.py dist/CodexBridge.app/Contents/Resources
printf '%s\n' 'Build: dist/CodexBridge.app (unsigned; signing and notarization not performed)'

#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "==================================================="
echo "  SCIA Magna 200 - Process Viewer (Starting...)"
echo "==================================================="

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 is not installed. Please install Python 3 first."
    exit 1
fi

if [ ! -d ".venv/bin" ]; then
    echo "[1/2] Creating Linux/macOS virtual environment (.venv)..."
    rm -rf .venv
    python3 -m venv .venv
    source .venv/bin/activate
    echo "[2/2] Installing required libraries..."
    pip install --disable-pip-version-check -r requirements.txt
else
    source .venv/bin/activate
fi

echo "Starting web server... Your browser will open automatically as soon as it is ready!"

# Abre o browser automaticamente em background assim que a porta 8050 responder (suporta macOS, Linux e WSL)
(
    for i in {1..60}; do
        if curl -s http://127.0.0.1:8050 >/dev/null 2>&1; then
            if command -v open >/dev/null 2>&1; then
                open "http://127.0.0.1:8050"
            elif command -v xdg-open >/dev/null 2>&1; then
                xdg-open "http://127.0.0.1:8050"
            elif command -v powershell.exe >/dev/null 2>&1; then
                powershell.exe -NoProfile -Command "Start-Process 'http://127.0.0.1:8050'" >/dev/null 2>&1
            fi
            break
        fi
        sleep 0.5
    done
) &

python3 app_scia.py

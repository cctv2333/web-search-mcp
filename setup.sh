#!/usr/bin/env bash
# setup.sh - Linux / cloud install & self-test (mirror of setup.bat)
# Usage:  chmod +x setup.sh && ./setup.sh
set -e
cd "$(dirname "$0")"

echo "[1/3] create venv .venv ..."
python3 -m venv .venv

echo "[2/3] pip install -r requirements.txt ..."
.venv/bin/pip install --disable-pip-version-check -q -r requirements.txt

echo "[3/3] run test_self.py ..."
.venv/bin/python test_self.py

echo
echo "Done. Cloud tips:"
echo "  - export TZ=Asia/Shanghai   # else timestamps use server local (UTC by default)"
echo "  - export TAVILY_API_KEY=...  # optional, better search fallback; ws_search provider=auto"
echo "  - browser fallback: apt install chromium  (absent => only one less fallback, no crash)"
echo "  - stdio transport works when agent runs on the SAME host; cross-machine needs HTTP/SSE + auth"

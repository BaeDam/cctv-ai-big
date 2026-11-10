#!/bin/sh
# Jikyeobom CCTV demo - local server for webcam (macOS/Linux)
cd "$(dirname "$0")"
( sleep 1; open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null ) &
python3 -m http.server 8000 --bind 127.0.0.1

#!/bin/bash
# Linux/macOS terminal: ./start.sh   (starts LeadPilot; first run sets everything up)
cd "$(dirname "$0")" || exit 1
PY=""
for candidate in python3.14 python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.12 or newer is required. Install it from https://www.python.org/downloads/ and double-click this again."
else
  "$PY" run.py "$@"
fi
echo
read -r -p "Press Enter to close this window..." _

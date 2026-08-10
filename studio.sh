#!/usr/bin/env bash
# Webtoon Translation Studio - Masaüstü Launcher Başlatıcı

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -f "$DIR/.venv-ai/bin/python" ]; then
    PYTHON_BIN="$DIR/.venv-ai/bin/python"
else
    PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" "$DIR/control_panel.py" "$@"

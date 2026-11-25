#!/bin/sh
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if [ -z "${INKHUB_PYTHON:-}" ]; then
    if [ -x "$root/.venv/bin/python" ]; then
        INKHUB_PYTHON="$root/.venv/bin/python"
    else
        INKHUB_PYTHON=python3
    fi
fi
export INKHUB_PYTHON
if ! "$INKHUB_PYTHON" -c 'import sys; from PIL import Image; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    printf '%s\n' '墨枢需要 Python 3.10+ 和 Pillow。' >&2
    printf 'cd "%s"\npython3 -m venv .venv\n.venv/bin/python -m pip install -r requirements.txt\n' "$root" >&2
    exit 1
fi
exec "$root/note4-screen-scheduler" "$@"

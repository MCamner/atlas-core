#!/bin/sh
set -e
test -n "$TARGET" || { echo "TARGET saknas" >&2; exit 2; }
rsync -a ./build/ "$TARGET"

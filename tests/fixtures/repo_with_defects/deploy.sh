#!/bin/sh
# TODO: lägg till en kontroll av målmiljön innan detta körs skarpt
set -e
rsync -a ./build/ "$TARGET"

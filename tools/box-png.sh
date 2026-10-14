#!/bin/bash
#
# box-png.sh — draw shot.py's red callout boxes on a PNG that did not
# come out of a recording.
#
# Almost every lab figure is cut from a screen recording by shot.py,
# which draws the boxes as it cuts. A few cannot be: the recording
# never passes through that state, so the author takes a screenshot by
# hand. Those still need boxes, in the same red at the same weight, or
# the figure reads as a different kind of illustration.
#
#     tools/box-png.sh SRC DST x,y,w,h [x,y,w,h ...]
#
# Coordinates are in the SOURCE image's own pixels, which for a
# hand-taken screenshot is whatever the author's window was, NOT the
# 1920x1080 of the recordings. Check with `file SRC` first.
#
# SRC must be a pristine screenshot, not an already-boxed figure.
# Running this twice over its own output double-draws. Keep raw
# screenshots in shots-review/<module>/ (gitignored, same place the
# recordings live) and treat the copy under content/.../images/ as
# build output you can always regenerate.

set -euo pipefail

if [ "$#" -lt 3 ]; then
    sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
fi

src="$1"; shift
dst="$1"; shift

[ -f "$src" ] || { echo "no such file: $src" >&2; exit 1; }

# Kept in step with BOX_COLOR and BOX_THICKNESS in tools/shot.py. If
# you change one, change the other, or the hand-made figures stop
# matching the cut ones.
color="0xEE0000"
thickness=4

filter=""
for box in "$@"; do
    IFS=, read -r x y w h <<< "$box"
    [ -n "${h:-}" ] || { echo "box must be x,y,w,h: $box" >&2; exit 1; }
    [ -n "$filter" ] && filter="$filter,"
    filter="${filter}drawbox=x=${x}:y=${y}:w=${w}:h=${h}:color=${color}:t=${thickness}"
done

ffmpeg -nostdin -v error -i "$src" -vf "$filter" -frames:v 1 "$dst" -y
echo "$dst  ($# $([ "$#" -eq 1 ] && echo box || echo boxes))"

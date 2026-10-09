#!/usr/bin/env python3
"""Cut lab screenshots out of a screen recording, with red callout boxes.

Every image in the lab guide comes from a recording of someone actually
doing the steps, so no screenshot can show a state the product does not
produce. This turns "frame at 2:52, box around the service account
dropdown" into one command, and — more importantly — makes the NEXT
recording produce images that match the last batch: same red, same line
weight, same scale.

Three subcommands:

    # 1. find coordinates: writes a gridded frame to $TMPDIR and tells
    #    you the path. Grid lines every 100px, labelled every 200.
    shot.py probe --at 2:52

    # 2. cut the real thing
    shot.py grab --at 2:52 --out module-05/08-authorize-service-account \\
        --box 75,430,400,35

    # 3. check a batch in one glance instead of one read per image
    shot.py sheet --out /tmp/check.png module-05/0*.png

Boxes are `x,y,w,h` in SOURCE pixels (1920x1080 for the lab
recordings), which is what `probe` shows you. Repeat --box for several.

Requires ffmpeg on PATH. Nothing else — no PIL, no ImageMagick.
"""

import argparse
import glob
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(REPO, "content", "modules", "ROOT", "assets", "images")
DEFAULT_VIDEO = os.path.join(REPO, "ticket-enrichment-student-scenario.mp4")

# Red Hat red. Thick enough to survive the ~50% downscale Antora applies
# at width=100% on a laptop, thin enough not to cover the thing it marks.
BOX_COLOR = "#EE0000"
BOX_THICKNESS = 4

# Recordings are made against a live lab, so frames can carry real
# secrets — the AAP API token reveal dialog shows the token in clear
# text exactly once, and that frame is the one worth screenshotting.
# --redact paints a SOLID block over the region rather than blurring
# it: a blur of a short monospace string is not reliably irreversible,
# and a filled box obviously reads as "redacted" to the student.
REDACT_COLOR = "#3C3C3C"


def parse_time(value):
    """Accept 125, 2:05 or 1:02:05 and return seconds."""
    parts = str(value).split(":")
    if len(parts) > 3:
        raise argparse.ArgumentTypeError("bad timestamp: %s" % value)
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def parse_box(value):
    try:
        x, y, w, h = (int(n) for n in value.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            "--box wants x,y,w,h in source pixels, got %r" % value)
    return x, y, w, h


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        # ffmpeg puts everything on stderr; the last few lines are the
        # actual complaint and the rest is build configuration.
        sys.exit("ffmpeg failed:\n%s"
                 % "\n".join(result.stderr.strip().splitlines()[-12:]))


def extract(video, at, filters, destination):
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    run(["ffmpeg", "-nostdin", "-v", "error",
         # -ss before -i seeks on keyframes, which is fast and accurate
         # enough at 60fps: worst case lands a few hundredths early.
         "-ss", "%.3f" % at, "-i", video,
         "-frames:v", "1", "-update", "1",
         "-vf", ",".join(filters) if filters else "null",
         destination, "-y"])
    return destination


def cmd_probe(args):
    filters = [
        "drawgrid=w=100:h=100:t=1:c=cyan@0.45",
        "drawgrid=w=200:h=200:t=2:c=yellow@0.6",
    ]
    out = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                       "probe-%s.png" % str(args.at).replace(":", "-"))
    extract(args.video, parse_time(args.at), filters, out)
    print(out)
    print("cyan grid every 100px, yellow every 200px, origin top-left")


def cmd_grab(args):
    filters = []
    # Redactions first, so a callout box drawn around a secret field
    # still reads as a box around a redacted field rather than being
    # painted over.
    for x, y, w, h in args.redact or []:
        filters.append("drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=fill"
                       % (x, y, w, h, REDACT_COLOR))
    for x, y, w, h in args.box or []:
        filters.append(
            "drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=%d"
            % (x, y, w, h, BOX_COLOR, BOX_THICKNESS))
    if args.width:
        filters.append("scale=%d:-2" % args.width)

    name = args.out if args.out.endswith(".png") else args.out + ".png"
    destination = name if os.path.isabs(name) else os.path.join(IMAGES, name)
    extract(args.video, parse_time(args.at), filters, destination)

    print(os.path.relpath(destination, REPO))
    # The asciidoc line, so it can be pasted straight into the module.
    rel = os.path.relpath(destination, IMAGES)
    print('image::%s[title="", link=self, window=blank, width=100%%]' % rel)


def cmd_sheet(args):
    """Tile several finished screenshots into one image to eyeball."""
    paths = []
    for pattern in args.images:
        candidate = (pattern if os.path.isabs(pattern)
                     else os.path.join(IMAGES, pattern))
        paths.extend(sorted(glob.glob(candidate)) or [candidate])
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        sys.exit("no such image(s):\n  %s" % "\n  ".join(missing))

    columns = args.columns
    rows = -(-len(paths) // columns)
    inputs = []
    for path in paths:
        inputs += ["-i", path]
    # Pad each tile to a fixed box first: tile= refuses inputs of
    # differing sizes, and a cropped screenshot is a different size.
    scale = ("scale=%d:-1:force_original_aspect_ratio=decrease,"
             "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0x202020"
             % (args.tile_width, args.tile_width,
                int(args.tile_width * 9 / 16)))
    chain = "".join("[%d:v]%s[t%d];" % (i, scale, i)
                    for i in range(len(paths)))
    chain += "".join("[t%d]" % i for i in range(len(paths)))
    chain += "concat=n=%d:v=1:a=0[c];[c]tile=%dx%d[out]" % (
        len(paths), columns, rows)

    run(["ffmpeg", "-nostdin", "-v", "error"] + inputs
        + ["-filter_complex", chain, "-map", "[out]",
           "-frames:v", "1", "-update", "1", args.out, "-y"])
    print("%s  (%d image%s, %dx%d)"
          % (args.out, len(paths), "" if len(paths) == 1 else "s",
             columns, rows))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", default=DEFAULT_VIDEO,
                        help="source recording (default: the ticket "
                             "enrichment capture)")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="gridded frame for finding boxes")
    probe.add_argument("--at", required=True)
    probe.set_defaults(func=cmd_probe)

    grab = sub.add_parser("grab", help="cut one lab screenshot")
    grab.add_argument("--at", required=True)
    grab.add_argument("--out", required=True,
                      help="path under content/.../images, e.g. "
                           "module-02/03-create-credential")
    grab.add_argument("--box", type=parse_box, action="append",
                      metavar="X,Y,W,H")
    grab.add_argument("--redact", type=parse_box, action="append",
                      metavar="X,Y,W,H",
                      help="paint a solid block over a region holding a "
                           "real secret")
    grab.add_argument("--width", type=int,
                      help="scale output to this width (default: native)")
    grab.set_defaults(func=cmd_grab)

    sheet = sub.add_parser("sheet", help="tile images for a quick check")
    sheet.add_argument("images", nargs="+")
    sheet.add_argument("--out", required=True)
    sheet.add_argument("--columns", type=int, default=3)
    sheet.add_argument("--tile-width", type=int, default=640)
    sheet.set_defaults(func=cmd_sheet)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

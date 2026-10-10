#!/usr/bin/env python3
"""Cut lab screenshots out of a screen recording, with red callout boxes.

Every image in the lab guide comes from a recording of someone actually
doing the steps, so no screenshot can show a state the product does not
produce. This turns "frame at 2:52, box around the service account
dropdown" into one command, and — more importantly — makes the NEXT
recording produce images that match the last batch: same red, same line
weight, same scale.

Four subcommands:

    # 1. find coordinates: writes a gridded frame to $TMPDIR and tells
    #    you the path. Grid lines every 100px, labelled every 200.
    shot.py probe --at 2:52

    # 2. tighten a rough region onto the pixels actually inside it
    shot.py fit --at 2:52 --region 700,560,560,80

    # 3. cut the real thing. --fit takes a ROUGH region and shrinks it
    #    to the ink before drawing; --box takes exact coordinates.
    shot.py grab --at 2:52 --out module-05/08-authorize-service-account \\
        --fit 70,420,420,50

    # 4. check a batch in one glance instead of one read per image
    shot.py sheet --out /tmp/check.png module-05/0*.png

Boxes are `x,y,w,h` in SOURCE pixels (1920x1080 for the lab
recordings), which is what `probe` shows you. Repeat --box/--fit for
several.

Every `grab` also writes a PROOF image to $TMPDIR: the whole frame,
then one zoomed crop per box. Read that instead of the screenshot to
check a box, because at 1920 wide a box that is 15px low looks fine
and at 3x it obviously is not.

Requires ffmpeg on PATH. Nothing else — no PIL, no ImageMagick.
"""

import argparse
import glob
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(REPO, "content", "modules", "ROOT", "assets", "images")
# The second take of the ticket enrichment capture. Same session as the
# first, re-exported with the mouse cursor suppressed: the pointer kept
# landing on the thing a callout was pointing at, and a frame grabbed
# mid-move caught it as a smear.
DEFAULT_VIDEO = os.path.join(REPO, "shots-review",
                             "ticket-enrichment-student-scenario_2.mp4")

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

# How much white space to leave between the red line and the thing it
# is around. Has to clear BOX_THICKNESS, since drawbox grows the border
# inward from the rectangle you give it, or the line sits on the glyphs.
FIT_PAD = 8
# A pixel counts as ink if it is this far off the region's background
# value. Low enough for grey placeholder text on white, high enough to
# ignore JPEG-ish ringing around glyph edges.
FIT_THRESHOLD = 36
# Rows and columns that are almost entirely ink are table rules, panel
# borders and underlines, not content. Left in, a single 1px border
# stretches the box across the whole panel.
FIT_LINE_RATIO = 0.9
# Zoom target for proof crops. Wide boxes end up shrunk, which is fine:
# a 1700px box being 10px off is not the failure mode worth catching.
PROOF_WIDTH = 1280


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


def frame_size(video):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", video],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("ffprobe could not read %s" % video)
    width, height = result.stdout.strip().split("x")
    return int(width), int(height)


def gray_pixels(image, x, y, w, h):
    """One byte of luma per pixel for a rectangle of an image.

    ffmpeg is already a dependency and can hand back raw bytes, which
    is the whole reason this file needs no imaging library.
    """
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", image,
         "-vf", "crop=%d:%d:%d:%d,format=gray" % (w, h, x, y),
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True)
    if result.returncode != 0 or len(result.stdout) != w * h:
        sys.exit("could not read pixels at %d,%d,%d,%d:\n%s"
                 % (x, y, w, h, result.stderr.decode()[-400:]))
    return result.stdout


def fit_box(image, region, bounds, pad=FIT_PAD, threshold=FIT_THRESHOLD,
            keep_lines=False, quiet=False):
    """Shrink a roughly-drawn region onto the content inside it.

    Reading coordinates off a grid gets the neighbourhood right and the
    edges wrong, every time: the box ends up centred on where the label
    looked like it was rather than where its pixels are. This measures
    instead. Give it a region that generously contains the target and
    nothing else, and it returns the tight box plus padding.
    """
    x, y, w, h = clip_box(region, bounds)
    data = gray_pixels(image, x, y, w, h)

    histogram = [0] * 256
    for value in data:
        histogram[value] += 1
    background = histogram.index(max(histogram))

    rows = [0] * h
    columns = [0] * w
    for index, value in enumerate(data):
        if abs(value - background) > threshold:
            rows[index // w] += 1
            columns[index % w] += 1

    dropped = 0
    if not keep_lines:
        for index, count in enumerate(rows):
            if count >= w * FIT_LINE_RATIO:
                rows[index] = 0
                dropped += 1
        for index, count in enumerate(columns):
            if count >= h * FIT_LINE_RATIO:
                columns[index] = 0
                dropped += 1

    marked_rows = [i for i, count in enumerate(rows) if count]
    marked_columns = [i for i, count in enumerate(columns) if count]
    if not marked_rows or not marked_columns:
        sys.exit("nothing but background inside %d,%d,%d,%d — wrong "
                 "frame, wrong place, or --threshold too high"
                 % (x, y, w, h))

    tight = (x + marked_columns[0] - pad,
             y + marked_rows[0] - pad,
             marked_columns[-1] - marked_columns[0] + 1 + 2 * pad,
             marked_rows[-1] - marked_rows[0] + 1 + 2 * pad)
    tight = clip_box(tight, bounds)

    # Content running right up to the region edge means the region cut
    # it off, so what comes back is a crop and not a measurement. Worth
    # shouting about: it looks exactly like a good fit in the numbers.
    touching = [edge for edge, hit in (
        ("left", marked_columns[0] == 0),
        ("right", marked_columns[-1] == w - 1),
        ("top", marked_rows[0] == 0),
        ("bottom", marked_rows[-1] == h - 1)) if hit]
    if touching:
        print("  WARNING content reaches the %s of region %d,%d,%d,%d — "
              "widen it, the fit is clipped"
              % (("/".join(touching),) + tuple(region)), file=sys.stderr)

    if not quiet:
        note = ", dropped %d rule line(s)" % dropped if dropped else ""
        print("  fit %d,%d,%d,%d -> %d,%d,%d,%d  (bg %d%s)"
              % (tuple(region) + tight + (background, note)),
              file=sys.stderr)
    return tight


def clip_box(box, bounds):
    x, y, w, h = box
    width, height = bounds
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        sys.exit("box %d,%d,%d,%d falls outside the %dx%d frame"
                 % (box + bounds))
    return x0, y0, x1 - x0, y1 - y0


def check_box(box, bounds, label):
    """Refuse coordinates that cannot be right before drawing them."""
    x, y, w, h = box
    width, height = bounds
    if x < 0 or y < 0 or x + w > width or y + h > height:
        sys.exit("%s %d,%d,%d,%d runs off the %dx%d frame. Coordinates "
                 "read off a scaled contact sheet need converting back "
                 "to source pixels first."
                 % ((label,) + box + bounds))
    if w < 8 or h < 8:
        sys.exit("%s %d,%d,%d,%d is smaller than the border it draws"
                 % ((label,) + box))


def write_proof(image, boxes, destination, bounds):
    """Whole frame on top, then every box zoomed, in one tall image.

    A callout checked at full width always looks acceptable. The same
    callout at 3x shows the line cutting through descenders, or a
    column of white on one side and none on the other.
    """
    margin = 14
    crops = []
    for x, y, w, h in boxes:
        crops.append(clip_box((x - margin, y - margin,
                               w + 2 * margin, h + 2 * margin), bounds))

    chain = ("[0:v]scale=%d:-2,pad=iw:ih+10:0:0:color=0x303030[p0];"
             % PROOF_WIDTH)
    for index, (x, y, w, h) in enumerate(crops, start=1):
        chain += ("[0:v]crop=%d:%d:%d:%d,scale=%d:-2:flags=neighbor,"
                  "pad=iw:ih+10:0:0:color=0x303030[p%d];"
                  % (w, h, x, y, PROOF_WIDTH, index))
    count = len(crops) + 1
    chain += "".join("[p%d]" % i for i in range(count))
    chain += "vstack=inputs=%d[out]" % count

    run(["ffmpeg", "-nostdin", "-v", "error", "-i", image,
         "-filter_complex", chain, "-map", "[out]",
         "-frames:v", "1", "-update", "1", destination, "-y"])
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


def cmd_fit(args):
    bounds = frame_size(args.video)
    at = parse_time(args.at)
    clean = extract(args.video, at, [],
                    os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                 "fit-source.png"))
    boxes = [fit_box(clean, region, bounds, pad=args.pad,
                     threshold=args.threshold, keep_lines=args.keep_lines,
                     quiet=True)
             for region in args.region]
    for box in boxes:
        print("--box %d,%d,%d,%d" % box)
    proof = extract(args.video, at,
                    ["drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=%d"
                     % (box + (BOX_COLOR, BOX_THICKNESS)) for box in boxes],
                    os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                 "fit-preview.png"))
    print(write_proof(proof, boxes,
                      os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                   "fit-proof.png"), bounds))


def cmd_grab(args):
    bounds = frame_size(args.video)
    at = parse_time(args.at)

    boxes = list(args.box or [])
    for box in boxes:
        check_box(box, bounds, "--box")
    if args.fit:
        # One clean extraction of the same frame the screenshot comes
        # from, measured before anything is drawn on it. Measuring the
        # drawn frame would find the boxes from the previous pass.
        clean = extract(args.video, at, [],
                        os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                     "fit-source.png"))
        for region in args.fit:
            check_box(region, bounds, "--fit")
            boxes.append(fit_box(clean, region, bounds, pad=args.pad,
                                 threshold=args.threshold,
                                 keep_lines=args.keep_lines))

    filters = []
    # Redactions first, so a callout box drawn around a secret field
    # still reads as a box around a redacted field rather than being
    # painted over.
    for box in args.redact or []:
        check_box(box, bounds, "--redact")
        filters.append("drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=fill"
                       % (box + (REDACT_COLOR,)))
    for box in boxes:
        filters.append("drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=%d"
                       % (box + (BOX_COLOR, BOX_THICKNESS)))
    if args.width:
        filters.append("scale=%d:-2" % args.width)

    name = args.out if args.out.endswith(".png") else args.out + ".png"
    destination = name if os.path.isabs(name) else os.path.join(IMAGES, name)
    extract(args.video, at, filters, destination)

    print(os.path.relpath(destination, REPO))
    # The asciidoc line, so it can be pasted straight into the module.
    rel = os.path.relpath(destination, IMAGES)
    print('image::%s[title="", link=self, window=blank, width=100%%]' % rel)
    # The resolved coordinates, so a --fit run can be pinned to exact
    # --box values once it is approved.
    if boxes:
        print(" ".join("--box %d,%d,%d,%d" % box for box in boxes))
    if boxes and not args.no_proof:
        proof = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                             "proof-%s.png" % os.path.basename(rel))
        print(write_proof(destination, boxes, proof, bounds))


def read_shot_list(path):
    """Parse a shot list: `<time> <name> <box> <box> ...` per line.

    The coordinates are the expensive part of this job, so they live in
    a file next to the tool rather than in shell history. Re-cutting
    every image after a new export of the recording is then one
    command, and a diff shows which callouts moved.
    """
    shots = []
    with open(path) as handle:
        for number, line in enumerate(handle, start=1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) < 2:
                sys.exit("%s:%d: want `<time> <name> [box ...]`"
                         % (path, number))
            at, name = fields[0], fields[1]
            try:
                boxes = [parse_box(field) for field in fields[2:]]
            except argparse.ArgumentTypeError as problem:
                sys.exit("%s:%d: %s" % (path, number, problem))
            shots.append((at, name, boxes))
    return shots


def cmd_batch(args):
    bounds = frame_size(args.video)
    for at, name, boxes in read_shot_list(args.list):
        for box in boxes:
            check_box(box, bounds, "%s box" % name)
        filters = ["drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=%d"
                   % (box + (BOX_COLOR, BOX_THICKNESS)) for box in boxes]
        destination = os.path.join(IMAGES, args.prefix, name + ".png")
        extract(args.video, parse_time(at), filters, destination)
        print("%-34s @%-5s %d box%s"
              % (name, at, len(boxes), "" if len(boxes) == 1 else "es"))


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

    def add_fit_options(parser):
        parser.add_argument("--pad", type=int, default=FIT_PAD,
                            help="white space between the line and the "
                                 "content (default: %d)" % FIT_PAD)
        parser.add_argument("--threshold", type=int, default=FIT_THRESHOLD,
                            help="how far off the background a pixel has "
                                 "to be to count as content (default: %d)"
                                 % FIT_THRESHOLD)
        parser.add_argument("--keep-lines", action="store_true",
                            help="treat table rules and panel borders as "
                                 "content instead of ignoring them")

    fit = sub.add_parser("fit", help="tighten a rough region onto its content")
    fit.add_argument("--at", required=True)
    fit.add_argument("--region", type=parse_box, action="append",
                     required=True, metavar="X,Y,W,H",
                     help="a region that generously contains the target "
                          "and nothing else")
    add_fit_options(fit)
    fit.set_defaults(func=cmd_fit)

    grab = sub.add_parser("grab", help="cut one lab screenshot")
    grab.add_argument("--at", required=True)
    grab.add_argument("--out", required=True,
                      help="path under content/.../images, e.g. "
                           "module-02/03-create-credential")
    grab.add_argument("--box", type=parse_box, action="append",
                      metavar="X,Y,W,H", help="exact callout coordinates")
    grab.add_argument("--fit", type=parse_box, action="append",
                      metavar="X,Y,W,H",
                      help="a rough region to shrink onto its content "
                           "before drawing the callout")
    grab.add_argument("--redact", type=parse_box, action="append",
                      metavar="X,Y,W,H",
                      help="paint a solid block over a region holding a "
                           "real secret")
    grab.add_argument("--width", type=int,
                      help="scale output to this width (default: native)")
    grab.add_argument("--no-proof", action="store_true",
                      help="skip the zoomed check image")
    add_fit_options(grab)
    grab.set_defaults(func=cmd_grab)

    batch = sub.add_parser("batch", help="re-cut a whole module from a list")
    batch.add_argument("list", help="file of `<time> <name> [x,y,w,h ...]`")
    batch.add_argument("--prefix", default="",
                       help="image subdirectory, e.g. module-05")
    batch.set_defaults(func=cmd_batch)

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

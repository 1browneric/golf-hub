#!/usr/bin/env python3
"""Build a mental-training course JSON from a generated tracker page.

PROVENANCE, AND WHY THIS SCRIPT EXISTS AT ALL
---------------------------------------------
The per-hole walkthroughs are only allowed to say things that are true. The
osm-course-book pipeline (Overpass features, Esri imagery, USGS 3DEP lidar)
already ran against these courses and baked its output into the tracker page
at course/<slug>/index.html:

    HOLES        par, stroke index, per-tee yardages
    BOOK[n].haz  green-side bunkers by side, lateral penalty sides, water short
    BOOK[n].notes  the lidar green-slope read
    BOOK[n].fall   the green fall-line vector
    HOLE_INTEL     the prose the tracker already shows for the same geometry

So the geometry is not re-derived here and it is never guessed - it is lifted
from the committed pipeline output, which is the same source the round tracker
reads. This script is the audit trail for that claim.

Two strategy fields cannot come from geometry alone. `fat_side` and
`ideal_leave` are computed from the trouble map by a stated, conservative rule
and are tagged `"derived": true` so Eric can overwrite them from his own
memory of the hole. `shape` is left empty: a dogleg direction is NOT resolvable
from the committed data (clubmap carries the frame scale and the tee/green
anchors, not the fairway centreline), and inventing one is exactly what the
hard rule forbids. Empty shape fields are reported as gaps.

Usage:
    python3 scripts/extract_course_holes.py                 # all known courses
    python3 scripts/extract_course_holes.py paradise-pointe-posse
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "knowledge" / "golf" / "mental-training" / "courses"

# slug -> the tee whose yardages the course book is anchored to. The generated
# trackers say so themselves: `const TEES = [...];  // Blue = the anchor`.
COURSES = {
    "paradise-pointe-posse": "Blue",
    "paradise-pointe-outlaw": "Blue",
    "shoal-creek": "Blue",
}

ANCHOR_KEY = "blue"


# ---------------------------------------------------------------- parsing


# The generator emits some constants as real JSON (BOOK, HOLE_INTEL, COURSE)
# and others as hand-written JS object literals with bare keys (ROUND, HOLES).
# Only the literals need repair, so the repair runs as a fallback and never
# touches a payload that already parsed - which matters, because BOOK is
# megabytes of base64 that a blind regex would happily corrupt.
_BARE_KEY = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:")


def _const(src: str, name: str):
    """Pull `const NAME = <object or array>;` out of a generated tracker page."""
    m = re.search(r"const %s\s*=\s*(\{.*?\}|\[.*?\]);\n" % name, src, re.S)
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(_BARE_KEY.sub(r'\1"\2":', raw))


def load_tracker(slug: str) -> dict:
    page = REPO / "course" / slug / "index.html"
    if not page.exists():
        raise SystemExit("no tracker page at %s" % page)
    src = page.read_text(encoding="utf-8")
    return {
        "round": _const(src, "ROUND"),
        "course": _const(src, "COURSE"),
        "holes": _const(src, "HOLES"),
        "book": _const(src, "BOOK"),
        "intel": _const(src, "HOLE_INTEL"),
    }


# ------------------------------------------------------- trouble + strategy

# The pipeline tags a green-side hazard with one of four sides. `front`/`back`
# are folded onto short/long so the phrasing below only has four cases.
SIDE_WORDS = {"left": "left", "right": "right", "short": "short",
              "long": "long", "front": "short", "back": "long"}

OPPOSITE = {"left": "right", "right": "left", "short": "long", "long": "short"}


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def trouble_text(haz: dict) -> str:
    """A factual sentence built only from tagged hazards. No hazard, no words."""
    if not haz:
        return ""
    parts = []

    lateral = [s for s in (haz.get("lateral") or []) if s in ("left", "right")]
    if lateral:
        parts.append("penalty area %s off the tee" % _join(
            ["down the " + s for s in lateral]))

    if haz.get("water_front"):
        parts.append("water short of the green")

    greenside = haz.get("green") or []
    bunkers = sorted({SIDE_WORDS.get(h.get("side"), h.get("side"))
                      for h in greenside
                      if h.get("type") == "bunker" and h.get("side")})
    water = sorted({SIDE_WORDS.get(h.get("side"), h.get("side"))
                    for h in greenside
                    if h.get("type") == "water" and h.get("side")})
    if water:
        parts.append("water %s of the green" % _join(water))
    if len(bunkers) >= 4:
        parts.append("bunkers ringing the green")
    elif bunkers:
        parts.append("%s %s of the green" % (
            "bunker" if len(bunkers) == 1 else "bunkers", _join(bunkers)))

    # `water_front` and a green-side water hazard tagged `short` describe the
    # same pond, so the same clause can land in the list twice.
    seen, uniq = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return "; ".join(uniq)


def fat_side(haz: dict, tee_shot: bool = True) -> tuple[str, bool]:
    """The conservative side, derived by aiming away from the dominant hazard.

    Rule, stated so it can be argued with: a penalty area outranks a bunker,
    because the penalty costs a stroke and the bunker costs a technique. Water
    short of the green outranks both and pushes the miss long. If the hazards
    cancel (both sides, or none tagged), the answer is the middle of the green,
    which is never wrong and never a guess.

    `tee_shot=False` ignores lateral tee-shot hazards, so a par 3 - where the
    tee shot IS the approach - gets a green-relative answer.
    """
    if not haz:
        return "middle of the green", True

    lateral = [s for s in (haz.get("lateral") or []) if s in ("left", "right")]
    if tee_shot and len(lateral) == 1:
        return OPPOSITE[lateral[0]] + " side of the fairway", True

    # left/right read as a side; short/long read as a half, which is how the
    # miss is actually described standing over the shot.
    half = {"left": "left side of the green", "right": "right side of the green",
            "short": "front half of the green", "long": "back half of the green"}

    greenside = haz.get("green") or []
    water = [SIDE_WORDS.get(h.get("side"), h.get("side"))
             for h in greenside if h.get("type") == "water"]
    water = [s for s in water if s in OPPOSITE]
    # No qualifier is appended here ("back half of the green - never short" and
    # the like). fat_side is dropped into the middle of sentences by the
    # walkthrough generator, and a trailing dash clause derails every one of
    # them. The trouble sentence already says where the water is.
    if len(set(water)) == 1:
        return half[OPPOSITE[water[0]]], True

    if haz.get("water_front"):
        return half["long"], True

    bunkers = [h.get("side") for h in greenside if h.get("type") == "bunker"]
    sides = [s for s in bunkers if s in ("left", "right")]
    if len(set(sides)) == 1:
        return OPPOSITE[sides[0]] + " side of the green", True
    if "short" in bunkers and "long" not in bunkers:
        return "back half of the green", True
    if "long" in bunkers and "short" not in bunkers:
        return "front half of the green", True

    return "middle of the green", True


# Eric's actual wedge carries, from My Bag in the hub. A "full wedge number" is
# one of these, not a half swing - the point of laying back is to have a stock
# shot left.
FULL_WEDGES = [("58 degree", 95), ("56 degree", 103), ("52 degree", 114),
               ("48 degree", 127), ("pitching wedge", 138)]


def ideal_leave(par: int, yardage: int, haz: dict) -> tuple[str, bool]:
    """A conservative leave, derived from par and the tee-to-green number."""
    if par == 3:
        # On a par 3 the tee shot is the approach, so the leave IS the fat side.
        side, _ = fat_side(haz, tee_shot=False)
        return "the " + side if not side.startswith("the ") else side, True

    if par == 5:
        # Lay back to a full wedge on the third rather than a half shot.
        club, num = FULL_WEDGES[2]          # 52 degree, 114
        return "a full %s from about %d yards" % (club, num), True

    # Par 4: what is left after a normal drive decides the number. Anything
    # that lands inside a stock wedge stays a stock wedge; longer holes leave
    # a mid iron and the honest answer is the fat side, not a wedge number.
    approach = yardage - 250
    if approach <= 90:
        return "a stock %s - do not walk it inside 90 yards" % FULL_WEDGES[0][0], True
    for club, num in FULL_WEDGES:
        if approach <= num + 8:
            return "a full %s from about %d yards" % (club, num), True
    side, _ = fat_side(haz)
    return "a mid iron into the %s" % side, True


def green_notes(book_hole: dict, intel_hole: dict) -> str:
    """Lidar slope plus any false-front warning. Both are pipeline output.

    The two sources overlap - HOLE_INTEL.gnote is often a verbatim copy of a
    line already in BOOK.notes - so identical lines are collapsed rather than
    read out twice.
    """
    notes = list(book_hole.get("notes") or [])
    gnote = (intel_hole or {}).get("gnote") or ""
    if gnote:
        notes.append(gnote)
    seen, out = set(), []
    for n in notes:
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return " ".join(out)


# ------------------------------------------------------------------ build


def build(slug: str) -> tuple[dict, list[str]]:
    t = load_tracker(slug)
    holes_src, book, intel = t["holes"], t["book"] or {}, t["intel"] or {}
    if not holes_src:
        raise SystemExit("%s: no HOLES array in the tracker" % slug)

    gaps: list[str] = []
    holes = []
    for h in holes_src:
        n = h["n"]
        yds = (h.get("yds") or {}).get(ANCHOR_KEY)
        b = book.get(str(n)) or {}
        i = intel.get(str(n)) or {}
        haz = b.get("haz") or {}

        if yds is None:
            gaps.append("hole %d: no %s yardage in the tracker - hole omitted"
                        % (n, COURSES[slug]))
            continue
        if not b:
            gaps.append("hole %d: no course-book entry - hole omitted" % n)
            continue

        trouble = trouble_text(haz)
        if not trouble:
            gaps.append("hole %d: no hazard tagged by the pipeline; trouble "
                        "left empty rather than invented" % n)

        fs, fs_derived = fat_side(haz, tee_shot=h["par"] != 3)
        il, il_derived = ideal_leave(h["par"], yds, haz)
        gn = green_notes(b, i)
        if not gn:
            gaps.append("hole %d: no lidar green read - green_notes empty" % n)

        # shape is NOT derivable from the committed pipeline output. Left empty
        # on purpose and reported, per the never-invent rule.
        gaps.append("hole %d: dogleg shape not resolvable from committed "
                    "geometry - shape left empty" % n)

        holes.append({
            "hole": n,
            "par": h["par"],
            "yardage": yds,
            "shape": "",
            "trouble": trouble,
            "fat_side": fs,
            "ideal_leave": il,
            "green_notes": gn,
            "derived": bool(fs_derived or il_derived),
        })

    doc = {
        "course": (t["course"] or {}).get("name") or (t["round"] or {}).get("course") or slug,
        "tees": COURSES[slug],
        "source": "osm-course-book output committed at course/%s/index.html" % slug,
        "holes": holes,
    }
    return doc, gaps


def main(argv: list[str]) -> int:
    slugs = argv[1:] or list(COURSES)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug in slugs:
        if slug not in COURSES:
            print("skip %s: not a known course-book course" % slug)
            continue
        try:
            doc, gaps = build(slug)
        except SystemExit as e:
            print("skip %s: %s" % (slug, e))
            continue
        out = OUT_DIR / ("%s.json" % slug)
        out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print("%s -> %s (%d holes, tees %s)"
              % (slug, out.relative_to(REPO), len(doc["holes"]), doc["tees"]))
        shape_gaps = [g for g in gaps if "shape left empty" in g]
        other = [g for g in gaps if "shape left empty" not in g]
        if shape_gaps:
            print("   gap: dogleg shape unresolved on %d holes "
                  "(not in the committed geometry)" % len(shape_gaps))
        for g in other:
            print("   gap: %s" % g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

# Mental Training — handoff

## State as of this writing

- `main` has the feature merged: session scripts, 54 per-hole walkthroughs,
  the Improvement-tab card (top of the tab, collapsed by default), and three
  scripts under `scripts/`.
- Last three commits on `main`: `aa43f20` (card moved to top), `042fced`,
  `69fb7fd` (feature).
- **Audio is NOT on `main`.** `git ls-tree -r origin/main -- assets/audio`
  returns nothing. The TTS render either ran locally without a commit, or was
  pushed to a branch that has not merged. This is the first thing to resolve.
- Live site (`https://1browneric.github.io/golf-hub/`) could not be verified
  from the previous sandbox — GitHub Pages is blocked by the egress policy
  there. Verify from a session that can reach it, or on device.

## The one-writer / do-not-touch rule still applies

Do not touch: the round save pipeline, `GolfTracker_Post.gs`, the Apps Script
project, Pencil Wedge, or anything under Garrett's Hub. This feature is
self-contained under `knowledge/golf/mental-training/`, `scripts/`, and
`assets/audio/mental-training/`, plus one baked block in `index.html`.

## Task 1 — land the audio (highest priority)

1. Find the MP3s from the VM render. Expected layout:
   - `assets/audio/mental-training/*.mp3`            (7 session files)
   - `assets/audio/mental-training/courses/<slug>/h01.mp3 …`  (per hole)
   - `assets/audio/mental-training/.hashes/*.sha256` (idempotency sidecars)
2. If they are only on the VM: copy them into the repo at those paths, on a
   branch off latest `main` (keep the branch name the delivery flow expects),
   commit, push, open a PR, merge.
3. `.gitignore` note: the repo ignores `course/**/*.webp` and `assets.js`, NOT
   the audio dir — MP3s are meant to be committed. Confirm none are ignored
   with `git check-ignore assets/audio/mental-training/01-the-routine.mp3`
   (should print nothing).
4. Size budget: keep total added audio under ~40 MB. `mental_training_tts.py`
   prints the running total and fails if it exceeds the budget.

## Task 2 — verify the render matched intent

The scripts are the source of truth; the MP3s are derived. Confirm:

- Voice: the calmest premium male en-US voice actually present on the project.
  `python3 scripts/mental_training_tts.py --voices` lists what is available.
  The config block at the top of that file holds `VOICE_NAME` and
  `SPEAKING_RATE` (0.85) as one-line changes. If a different voice was chosen
  on the VM, set `VOICE_NAME` to it and re-run so the hash sidecars match.
- Pause handling: `> Pause` cue lines render as 6s of silence; cues that say
  "let the scene build" / "assemble" / "N reps" get 10s; paragraphs get an
  800ms beat. Spot-check one session audio against its markdown.
- Re-runs are idempotent: unchanged scripts are skipped via the `.sha256`
  sidecars. A voice or rate change re-renders (the hash covers the settings).

## Task 3 — verify on device / on the live site

1. Improvement tab → Mental Training is the FIRST card (tagged MENTAL REPS).
2. Open it: intro text, six session rows, then Course Walkthroughs.
3. A session with audio present shows a working `<audio>` player above the
   script. A session without audio collapses the player to a line of text —
   that fallback is by design, not a bug.
4. Course Walkthroughs: Posse and Outlaw expand to 18 hole rows each; Shoal
   Creek too. Any Course, Charleston National, and Lake Shawnee show
   "No walkthrough built yet." (they have no walkthrough JSON).
5. No red/green status colours anywhere in the section; no emojis. If you add
   anything, hold that line (Eric is red-green colourblind).

## The scripts, and how to re-run them

All three are pure-stdlib except the TTS auth path (google-auth) and live in
`scripts/`. Run from the repo root.

- `extract_course_holes.py [slug …]`
  Rebuilds `knowledge/golf/mental-training/courses/<slug>.json` from the
  committed osm-course-book output inside `course/<slug>/index.html`. Geometry
  (par, yardage, hazard map, lidar green read) is LIFTED, never guessed.
  `fat_side` / `ideal_leave` are derived by a conservative rule and tagged
  `"derived": true`. `shape` (dogleg direction) is not in the committed
  geometry — left empty and reported as a gap, never invented. Known courses:
  paradise-pointe-posse, paradise-pointe-outlaw, shoal-creek.

- `course_walkthrough.py [slug …] [--no-audio] [--no-inject] [--force]`
  Builds one 60–90s markdown per hole, renders each through the TTS pipeline,
  writes a per-course `manifest.json`, and bakes ALL session + walkthrough
  text into `index.html` between the `MENTAL-TRAINING:BEGIN/END` markers.
  `--no-audio` writes text + manifest only (what the sandbox used). Re-run
  WITHOUT `--no-audio` on a box with Google Cloud creds to attach hole audio.

- `mental_training_tts.py [--force] [--voices]`
  Renders the seven session scripts to MP3. `--force` re-renders everything;
  default skips unchanged scripts via the hash sidecars.

### If you edit a session script or a hole's wording

Because the hub text is BAKED into `index.html`, a wording change is not live
until you re-bake:

```
python3 scripts/course_walkthrough.py            # re-renders audio + re-bakes
# or, text only (no creds needed):
python3 scripts/course_walkthrough.py --no-audio
```

Then commit `index.html` along with the changed markdown/audio.

## Known gaps to hand Eric, not fix silently

- Dogleg `shape` empty on all 54 holes (not in committed geometry).
- `trouble` empty on Posse 4 and Shoal Creek 17 (pipeline tagged no hazard).
- `fat_side` / `ideal_leave` are conservative DERIVED defaults on every hole
  (`"derived": true`) — Eric may want to refine these from his own read of the
  courses before the weekend round.
- New courses need: a `<slug>.json` (via `extract_course_holes.py` if the
  tracker carries course-book geometry, else hand-authored to the schema),
  then `course_walkthrough.py <slug>`.

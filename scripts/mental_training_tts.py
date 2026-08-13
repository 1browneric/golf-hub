#!/usr/bin/env python3
"""Render the mental-training session scripts to MP3 with Google Cloud TTS.

    python3 scripts/mental_training_tts.py            # render anything changed
    python3 scripts/mental_training_tts.py --force    # re-render everything
    python3 scripts/mental_training_tts.py --voices   # list the premium en-US
                                                      # male voices on the project

Source of truth is knowledge/golf/mental-training/*.md. Output is one MP3 per
session in assets/audio/mental-training/, named to match the markdown file, so
01-the-routine.md becomes 01-the-routine.mp3 and the hub can build the audio
src from the session slug alone.

AUTH. Application Default Credentials - on the VM that is the attached service
account, so there is nothing to configure. The only dependency beyond the
standard library is google-auth (pip install google-auth); the HTTP itself is
urllib, deliberately, so this keeps working on a box that does not have the
google-cloud-texttospeech client installed. If texttospeech.googleapis.com is
disabled on the project the first call fails with SERVICE_DISABLED and the
script enables it through gcloud and retries once.

This module is also imported by scripts/course_walkthrough.py, which reuses
`synthesize`, `ssml_from_markdown` and `describe` so the per-hole walkthroughs
come out in the same voice at the same pace as the sessions.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIG - voice and pace are one-line changes, on purpose.
# ---------------------------------------------------------------------------

# Preference order, calmest first. The script asks the API which voices the
# project actually has and takes the first of these that comes back, so a voice
# being retired degrades to the next one instead of failing the run. Run with
# --voices to see the full list before changing this.
#
# Studio-Q leads because the Studio tier is trained on long-form narration and
# reads with the least inflection of the premium male en-US voices - which is
# what a guided visualization wants. Neural2-J is the calm fallback; the
# Chirp3-HD voices are the newest tier but read more conversationally.
VOICE_PREFERENCE = [
    "en-US-Studio-Q",
    "en-US-Neural2-J",
    "en-US-Neural2-D",
    "en-US-Chirp3-HD-Charon",
    "en-US-Chirp3-HD-Orus",
]
VOICE_NAME = "en-US-Studio-Q"     # resolved against the project at run time
SPEAKING_RATE = 0.85
LANGUAGE_CODE = "en-US"

# Pause lengths for the `> Pause ...` cue lines.
PAUSE_SHORT = "6s"                # a plain cue
PAUSE_LONG = "10s"                # "let the scene build", or multiple reps
PARAGRAPH_BREAK = "800ms"         # sentence-level pacing between paragraphs

# The cue line becomes silence and is not read aloud - the narrator has already
# said what to do. Flip this to True to have the cue spoken before the break.
SPEAK_PAUSE_CUES = False

# Google returns mono MP3. It does not take a bitrate, so hitting the target
# needs a re-encode; if ffmpeg is missing the API's own MP3 ships as-is, which
# is smaller, not larger, so the size budget still holds.
MP3_BITRATE = "40k"
SAMPLE_RATE_HZ = 24000
TOTAL_SIZE_BUDGET_MB = 40

TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
VOICES_ENDPOINT = "https://texttospeech.googleapis.com/v1/voices"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# The API caps a single request at 5000 bytes of SSML, so a session is
# synthesized in chunks and the MP3s are concatenated. Kept under the cap with
# room for the wrapper tags.
SSML_BUDGET = 4200

REPO = Path(__file__).resolve().parent.parent
SESSION_DIR = REPO / "knowledge" / "golf" / "mental-training"
AUDIO_DIR = REPO / "assets" / "audio" / "mental-training"
HASH_DIR = AUDIO_DIR / ".hashes"


# ---------------------------------------------------------------------------
# Markdown -> SSML
# ---------------------------------------------------------------------------

# A cue that wants the long pause: an explicit instruction to let the image
# form, or one that asks for more than one rep. `assemble` is matched on its
# own because the two "build the hole from memory" cues in Session 2 are worded
# differently ("let the hole assemble from memory" / "assemble the hole from
# memory") and both mean the same thing.
_LONG_CUE = re.compile(
    r"let the scene build|assemble|"
    r"\b(two|three|four|five|six|\d+)\s+(full\s+|more\s+)?reps?\b|"
    r"\beach rep\b",
    re.I,
)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _plain(text: str) -> str:
    """Strip the markdown that would otherwise be read out as punctuation."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)      # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)          # italic
    text = re.sub(r"`(.+?)`", r"\1", text)            # code
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)   # links
    # An em dash inside a sentence is a beat, and the voices read a bare dash
    # as nothing at all. A comma gets the pause without being spoken. The
    # interpunct is the course-name separator ("Paradise Pointe · Outlaw") and
    # gets the same treatment for the same reason.
    text = text.replace(" - ", ", ").replace(" — ", ", ").replace(" · ", ", ")
    return re.sub(r"\s+", " ", text).strip()


def strip_comments(markdown: str) -> str:
    """Drop HTML comments before a script is spoken, hashed or displayed.

    A comment in a session file is a note to whoever edits it next, not
    narration - 07-the-five.md carries one recording that its fifth item is a
    deliberate substitution for Fawcett's original, so a later reader does not
    "correct" it back. Every consumer strips at this one point, which is why
    the fingerprint below is taken on the stripped text: an edit to a note
    must not invalidate a rendered MP3 whose words did not change.
    """
    return re.sub(r"<!--.*?-->[ \t]*\n?", "", markdown, flags=re.S)


def ssml_blocks(markdown: str) -> list[str]:
    """Turn one session's markdown into an ordered list of SSML fragments."""
    out: list[str] = []
    for raw in re.split(r"\n\s*\n", strip_comments(markdown)):
        block = raw.strip()
        if not block:
            continue

        # `> Pause ...` - the cue line becomes silence.
        if block.lstrip().startswith(">"):
            cue = block.lstrip("> ").strip()
            if cue.lower().startswith("pause"):
                length = PAUSE_LONG if _LONG_CUE.search(cue) else PAUSE_SHORT
                if SPEAK_PAUSE_CUES:
                    out.append("%s<break time=\"%s\"/>"
                               % (_escape(_plain(cue)), length))
                else:
                    out.append("<break time=\"%s\"/>" % length)
                continue
            block = cue

        # Headings are read as a line of their own, then a beat.
        m = re.match(r"^#{1,6}\s+(.*)$", block)
        if m:
            out.append("%s<break time=\"%s\"/>"
                       % (_escape(_plain(m.group(1))), PARAGRAPH_BREAK))
            continue

        body = _escape(_plain(" ".join(block.splitlines())))
        if body:
            out.append("%s<break time=\"%s\"/>" % (body, PARAGRAPH_BREAK))
    return out


def ssml_from_markdown(markdown: str) -> list[str]:
    """Group the fragments into <speak> documents that fit one API request."""
    docs, buf, size = [], [], 0
    for frag in ssml_blocks(markdown):
        n = len(frag.encode("utf-8"))
        if buf and size + n > SSML_BUDGET:
            docs.append("<speak>%s</speak>" % "".join(buf))
            buf, size = [], 0
        buf.append(frag)
        size += n
    if buf:
        docs.append("<speak>%s</speak>" % "".join(buf))
    return docs


# ---------------------------------------------------------------------------
# Google Cloud Text-to-Speech
# ---------------------------------------------------------------------------

class TTSError(RuntimeError):
    pass


_token = None
_resolved_voice = None


def _access_token() -> str:
    global _token
    if _token is None:
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError:
            raise TTSError(
                "google-auth is not installed. pip install google-auth")
        creds, _ = google.auth.default(scopes=[SCOPE])
        creds.refresh(Request())
        _token = creds.token
    return _token


def _post(url: str, payload: dict | None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": "Bearer " + _access_token(),
                 "Content-Type": "application/json; charset=utf-8"},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _enable_api() -> bool:
    """Turn on texttospeech.googleapis.com. Returns True if that worked."""
    if not shutil.which("gcloud"):
        return False
    print("   texttospeech.googleapis.com is disabled - enabling it")
    r = subprocess.run(["gcloud", "services", "enable",
                        "texttospeech.googleapis.com"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("   could not enable it: %s" % r.stderr.strip())
        return False
    return True


def _call(url: str, payload: dict | None, _retried: bool = False) -> dict:
    try:
        return _post(url, payload)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if not _retried and e.code == 403 and "SERVICE_DISABLED" in body:
            if _enable_api():
                return _call(url, payload, _retried=True)
        raise TTSError("Text-to-Speech API %s: %s" % (e.code, body[:400]))


def resolve_voice() -> str:
    """Pick the first voice in VOICE_PREFERENCE the project actually offers."""
    global _resolved_voice
    if _resolved_voice:
        return _resolved_voice
    available = {v["name"] for v in
                 _call(VOICES_ENDPOINT + "?languageCode=" + LANGUAGE_CODE,
                       None).get("voices", [])}
    for name in ([VOICE_NAME] if VOICE_NAME in VOICE_PREFERENCE
                 else [VOICE_NAME] + VOICE_PREFERENCE):
        if name in available:
            _resolved_voice = name
            return name
    for name in VOICE_PREFERENCE:
        if name in available:
            print("   %s is not on this project - using %s" % (VOICE_NAME, name))
            _resolved_voice = name
            return name
    raise TTSError("none of the preferred voices exist on this project. "
                   "Run with --voices and set VOICE_NAME.")


def list_voices() -> None:
    voices = _call(VOICES_ENDPOINT + "?languageCode=" + LANGUAGE_CODE,
                   None).get("voices", [])
    rows = [v for v in voices
            if v.get("ssmlGender") == "MALE"
            and any(t in v["name"] for t in ("Studio", "Neural2", "Chirp3-HD"))]
    for v in sorted(rows, key=lambda x: x["name"]):
        print("  %-28s %s" % (v["name"], v.get("ssmlGender", "")))
    print("\n%d premium male en-US voices. VOICE_NAME is currently %s."
          % (len(rows), VOICE_NAME))


def synthesize(ssml_docs: list[str]) -> bytes:
    """Render SSML documents and return one concatenated MP3."""
    voice = resolve_voice()
    chunks = []
    for doc in ssml_docs:
        resp = _call(TTS_ENDPOINT, {
            "input": {"ssml": doc},
            "voice": {"languageCode": LANGUAGE_CODE, "name": voice},
            "audioConfig": {"audioEncoding": "MP3",
                            "speakingRate": SPEAKING_RATE,
                            "sampleRateHertz": SAMPLE_RATE_HZ},
        })
        chunks.append(base64.b64decode(resp["audioContent"]))
    return b"".join(chunks)


def _reencode(mp3: bytes) -> bytes:
    """Force mono at the target bitrate. No ffmpeg, no re-encode - not fatal."""
    if not shutil.which("ffmpeg"):
        return mp3
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-ac", "1", "-b:a", MP3_BITRATE, "-f", "mp3", "pipe:1"],
        input=mp3, capture_output=True)
    return r.stdout if r.returncode == 0 and r.stdout else mp3


# ---------------------------------------------------------------------------
# Duration, without pulling in an audio library
# ---------------------------------------------------------------------------

_BITRATES_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224,
                  256, 320, 0]
_BITRATES_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144,
                  160, 0]
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000],
          0: [11025, 12000, 8000]}


def mp3_duration(data: bytes) -> float:
    """Sum the frame durations. Correct for VBR as well as CBR."""
    i, total = 0, 0.0
    n = len(data)
    if data[:3] == b"ID3":                       # skip a leading ID3v2 tag
        size = ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14
                | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
        i = 10 + size
    while i + 4 <= n:
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        ver = (data[i + 1] >> 3) & 0x03          # 3 = MPEG1, 2 = MPEG2
        layer = (data[i + 1] >> 1) & 0x03        # 1 = Layer III
        bri = (data[i + 2] >> 4) & 0x0F
        sri = (data[i + 2] >> 2) & 0x03
        pad = (data[i + 2] >> 1) & 0x01
        if layer != 1 or ver == 1 or bri in (0, 15) or sri == 3:
            i += 1
            continue
        rate = _RATES.get(ver, _RATES[0])[sri]
        kbps = (_BITRATES_V1L3 if ver == 3 else _BITRATES_V2L3)[bri]
        spf = 1152 if ver == 3 else 576
        length = int((spf // 8) * kbps * 1000 / rate) + pad
        if length <= 0:
            i += 1
            continue
        total += spf / rate
        i += length
    return total


def describe(path: Path) -> str:
    data = path.read_bytes()
    secs = mp3_duration(data)
    return "%d:%02d  %.1f MB" % (int(secs // 60), int(secs % 60),
                                 len(data) / 1e6)


# ---------------------------------------------------------------------------
# Idempotent render
# ---------------------------------------------------------------------------

def _fingerprint(markdown: str) -> str:
    """Hash the script AND the settings that shape the audio.

    Hashing the source alone would leave a stale MP3 in place after a voice or
    speaking-rate change, which is the one thing a cache like this must not do.
    """
    h = hashlib.sha256()
    h.update(strip_comments(markdown).encode("utf-8"))
    h.update(("|".join([VOICE_NAME, str(SPEAKING_RATE), PAUSE_SHORT,
                        PAUSE_LONG, PARAGRAPH_BREAK, str(SPEAK_PAUSE_CUES),
                        MP3_BITRATE, str(SAMPLE_RATE_HZ)])).encode("utf-8"))
    return h.hexdigest()


def render_markdown(md_path: Path, out_path: Path, force: bool = False) -> str:
    """Render one markdown file to one MP3. Returns 'skip', 'ok' or an error."""
    markdown = md_path.read_text(encoding="utf-8")
    fp = _fingerprint(markdown)
    side = HASH_DIR / (out_path.stem + ".sha256")

    if (not force and out_path.exists() and side.exists()
            and side.read_text().strip() == fp):
        return "skip"

    audio = _reencode(synthesize(ssml_from_markdown(markdown)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(fp + "\n")
    return "ok"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="re-render even if the script is unchanged")
    ap.add_argument("--voices", action="store_true",
                    help="list the premium male en-US voices and exit")
    args = ap.parse_args(argv[1:])

    if args.voices:
        list_voices()
        return 0

    sessions = sorted(p for p in SESSION_DIR.glob("*.md"))
    if not sessions:
        print("no session scripts in %s" % SESSION_DIR)
        return 1

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    rendered = skipped = failed = 0
    for md in sessions:
        out = AUDIO_DIR / (md.stem + ".mp3")
        try:
            status = render_markdown(md, out, force=args.force)
        except TTSError as e:
            print("  %-28s FAILED  %s" % (md.name, e))
            failed += 1
            continue
        if status == "skip":
            print("  %-28s unchanged  %s" % (md.name, describe(out)))
            skipped += 1
        else:
            print("  %-28s rendered   %s" % (md.name, describe(out)))
            rendered += 1

    total = sum(p.stat().st_size for p in AUDIO_DIR.glob("*.mp3"))
    print("\n%d rendered, %d unchanged, %d failed" % (rendered, skipped, failed))
    print("session audio total: %.1f MB of a %d MB budget"
          % (total / 1e6, TOTAL_SIZE_BUDGET_MB))
    if total > TOTAL_SIZE_BUDGET_MB * 1e6:
        print("OVER BUDGET - lower MP3_BITRATE or SAMPLE_RATE_HZ")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

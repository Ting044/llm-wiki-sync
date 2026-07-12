#!/usr/bin/env python3
"""
export_anki_deck.py
===================
Collects flashcards from the `## 📇 记忆卡片` section of every literature note
and packages them into an Anki deck (.apkg).

Card syntax inside the section (same as the Obsidian Spaced Repetition plugin):
  问题::答案      → basic card
  问题:::答案     → basic + reversed card

Stable note GUIDs are derived from (citekey, front), so re-importing an
updated .apkg into Anki updates existing cards in place instead of
duplicating them, and your scheduling/review history is preserved.

Usage:
  python3 export_anki_deck.py --vault /path/to/vault [--out anki/LLM-Wiki.apkg]

Requirements:
  pip install genanki
"""

import argparse
import hashlib
import html
import json
import logging
import re
import sys
from pathlib import Path

import genanki

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

CARDS_HEADING = re.compile(r"^##\s+.*记忆卡片", re.M)
DECK_ID = 1626061889   # fixed so re-imports land in the same deck
MODEL_ID = 1626061890
MODEL_REV_ID = 1626061891

CSS = """
.card { font-family: "PingFang SC","Noto Sans SC",sans-serif; font-size: 19px;
        text-align: left; color: #1a1a2e; background: #fbfaf7; padding: 8px; }
.source { margin-top: 1.2em; font-size: 12px; color: #8a8fa3; }
.source a { color: #8a8fa3; }
"""

FIELDS = [{"name": "Front"}, {"name": "Back"}, {"name": "Source"}]
QFMT = "{{Front}}"
AFMT = '{{FrontSide}}<hr id="answer">{{Back}}<div class="source">{{Source}}</div>'

MODEL = genanki.Model(
    MODEL_ID, "LLM Wiki 文献卡片", fields=FIELDS, css=CSS,
    templates=[{"name": "Card", "qfmt": QFMT, "afmt": AFMT}],
)
MODEL_REV = genanki.Model(
    MODEL_REV_ID, "LLM Wiki 文献卡片(双向)", fields=FIELDS, css=CSS,
    templates=[
        {"name": "正→反", "qfmt": QFMT, "afmt": AFMT},
        {"name": "反→正", "qfmt": "{{Back}}",
         "afmt": '{{FrontSide}}<hr id="answer">{{Front}}<div class="source">{{Source}}</div>'},
    ],
)


def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    fm = {}
    if m:
        for line in m.group(1).split("\n"):
            km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
            if km:
                fm[km.group(1)] = km.group(2).strip().strip('"')
    return fm


def cards_section(text: str) -> str:
    """Return the body of the 记忆卡片 section (up to the next ## heading)."""
    m = CARDS_HEADING.search(text)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def parse_cards(section: str) -> list[tuple[str, str, bool]]:
    """Return (front, back, reversed) tuples from '问::答' / '问:::答' lines."""
    section = re.sub(r"%%.*?%%", "", section, flags=re.S)  # obsidian comments
    cards = []
    for line in section.splitlines():
        line = line.strip().lstrip("-").strip()
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        if ":::" in line:
            front, back = line.split(":::", 1)
            rev = True
        elif "::" in line:
            front, back = line.split("::", 1)
            rev = False
        else:
            continue
        if front.strip() and back.strip():
            cards.append((front.strip(), back.strip(), rev))
    return cards


def note_guid(citekey: str, front: str) -> str:
    return hashlib.sha256(f"{citekey}\x1f{front}".encode()).hexdigest()[:16]


def sanitize_tag(tag: str) -> str:
    return re.sub(r"[\s,]+", "_", tag.strip()) or "untagged"


def collect(vault: Path) -> list[genanki.Note]:
    notes_dir = vault / "LiteratureNotes"
    if not notes_dir.exists():
        logger.error(f"No LiteratureNotes/ in vault: {vault}")
        sys.exit(1)

    anki_notes = []
    for md in sorted(notes_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if fm.get("type") != "literature-note":
            continue
        citekey = fm.get("citekey", md.stem)
        cards = parse_cards(cards_section(text))
        if not cards:
            continue

        title = fm.get("title", citekey)
        link = fm.get("zotero_uri") or fm.get("url") or ""
        source = html.escape(f"{citekey} — {title}")
        if link:
            source = f'<a href="{html.escape(link)}">{source}</a>'

        for front, back, rev in cards:
            anki_notes.append(genanki.Note(
                model=MODEL_REV if rev else MODEL,
                fields=[html.escape(front), html.escape(back), source],
                guid=note_guid(citekey, front),
                tags=["LLM-Wiki", sanitize_tag(citekey)],
            ))
        logger.info(f"{md.name}: {len(cards)} card(s)")
    return anki_notes


def content_hash(notes: list[genanki.Note]) -> str:
    payload = sorted((n.guid, *n.fields) for n in notes)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser(description="Export literature-note flashcards to an Anki .apkg")
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault root")
    parser.add_argument("--out", default="anki/LLM-Wiki.apkg", help="Output .apkg path")
    parser.add_argument("--deck-name", default="LLM Wiki 文献卡片", help="Anki deck name")
    parser.add_argument("--force", action="store_true", help="Write even if cards are unchanged")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    out = Path(args.out)
    notes = collect(vault)
    if not notes:
        logger.info("No flashcards found — nothing to export.")
        return

    digest = content_hash(notes)
    stamp_file = out.with_suffix(".hash")
    if not args.force and stamp_file.exists() and stamp_file.read_text().strip() == digest:
        logger.info(f"Cards unchanged ({len(notes)} note(s)) — skipping export.")
        return

    deck = genanki.Deck(DECK_ID, args.deck_name)
    for n in notes:
        deck.add_note(n)

    out.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(deck).write_to_file(out)
    stamp_file.write_text(digest, encoding="utf-8")
    logger.info(f"Exported {len(notes)} note(s) → {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
sync_literature_notes.py
=======================
Syncs Zotero literature notes from a Better BibTeX .bib export to an Obsidian vault.

Architecture:
  Zotero → BBT auto-export .bib → GitHub repo → This script → Obsidian vault (LiteratureNotes/)
  → Obsidian Sync → All devices

Usage:
  python3 sync_literature_notes.py --bib /path/to/library.bib --vault /path/to/vault

Requirements:
  pip install bibtexparser python-dotenv
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import bibtexparser
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Frontmatter fields used in Obsidian literature notes ──────────────────────
FRONTMATTER_FIELDS = [
    "type",
    "title",
    "authors",
    "date",
    "year",
    "journal",
    "publisher",
    "doi",
    "url",
    "zotero_uri",
    "citekey",
    "tags",
    "abstract",
]


def load_env():
    """Load encrypted GitHub token from hermes credential store."""
    key_path = Path.home() / ".hermes" / "github_creds.key"
    creds_path = Path.home() / ".hermes" / "github_creds.enc"
    if not key_path.exists() or not creds_path.exists():
        return None
    try:
        from cryptography.fernet import Fernet

        with open(key_path, "rb") as f:
            key = f.read()
        with open(creds_path, "rb") as f:
            encrypted = f.read()
        return Fernet(key).decrypt(encrypted).decode()
    except Exception as e:
        logger.warning(f"Could not load GitHub token: {e}")
        return None


def sanitize_filename(name: str) -> str:
    """Remove characters illegal in file names."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


def parse_bibtex(bib_path: Path) -> list[dict]:
    """Parse a BibTeX file and return a list of entry dicts."""
    with open(bib_path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        logger.warning(f"Bib file is empty: {bib_path}")
        return []

    bib_db = bibtexparser.loads(content)
    entries = []
    for entry in bib_db.entries:
        # Normalise common fields
        entry["ID"] = entry.get("ID", "")
        entry["ENTRYTYPE"] = entry.get("ENTRYTYPE", "article")
        entries.append(entry)
    return entries


def build_frontmatter(entry: dict) -> str:
    """Build Obsidian-compatible YAML frontmatter from a BibTeX entry."""
    lines = ["---"]

    # Core fields
    lines.append(f"type: literature-note")
    lines.append(f"citekey: {entry.get('ID', '')}")

    title = entry.get("title", "").strip("{}{}".strip)
    if title:
        lines.append(f"title: \"{title}\"")

    # Authors (split on ' and ')
    authors = entry.get("author", "").replace("\n", " ").strip()
    if authors:
        author_list = [a.strip() for a in re.split(r"\s+and\s+", authors)]
        lines.append(f"authors: [{', '.join(author_list)}]")

    year = entry.get("year", "").strip()
    date = entry.get("date", year).strip()
    if year:
        lines.append(f"year: {year}")
    if date:
        lines.append(f"date: {date}")

    # Publication info
    for field in ["journal", "booktitle", "publisher", "doi", "url", "abstract"]:
        value = entry.get(field, "").strip()
        if value:
            # Strip LaTeX braces
            value = value.strip("{}{}".strip)
            lines.append(f"{field}: \"{value}\"")

    # Zotero URI
    zotero_uri = entry.get("uri", "").strip()
    if zotero_uri and "zotero.org" in zotero_uri:
        lines.append(f"zotero_uri: {zotero_uri}")

    # Tags (preserve existing or default)
    lines.append("tags: []")

    lines.append("---")
    return "\n".join(lines)


def entry_hash(entry: dict) -> str:
    """Quick hash of the fields that matter for change detection."""
    key_fields = ["ID", "title", "author", "year", "journal", "doi"]
    data = "|".join(str(entry.get(f, "")) for f in key_fields)
    return hashlib.sha256(data.encode()).hexdigest()[:12]


def sync_notes(bib_path: Path, vault_path: Path, dry_run: bool = False):
    """
    Main sync logic.

    For each entry in the .bib file:
      - Compute its citekey (= BibTeX ID)
      - Write (or overwrite) LiteratureNotes/<citekey>.md
      - The file content is: YAML frontmatter + abstract (if any)
    """
    vault = Path(vault_path).expanduser().resolve()
    notes_dir = vault / "LiteratureNotes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    state_file = vault / ".llm-wiki-sync-state.json"
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    entries = parse_bibtex(bib_path)
    logger.info(f"Parsed {len(entries)} entries from {bib_path}")

    changed = []
    for entry in entries:
        citekey = sanitize_filename(entry.get("ID", "unknown"))
        note_path = notes_dir / f"{citekey}.md"
        frontmatter = build_frontmatter(entry)
        content = frontmatter + "\n\n"

        # Append abstract as body if available
        abstract = entry.get("abstract", "").strip("{}{}".strip)
        if abstract:
            content += f"## Abstract\n{abstract}\n"

        new_hash = entry_hash(entry)

        if state.get(citekey, {}).get("hash") != new_hash:
            if dry_run:
                logger.info(f"[DRY-RUN] Would update: {note_path.name}")
            else:
                note_path.write_text(content, encoding="utf-8")
                logger.info(f"Updated: {note_path.name}")
            changed.append(citekey)

        state[citekey] = {
            "hash": new_hash,
            "path": str(note_path.relative_to(vault)),
            "synced_at": datetime.now().isoformat(),
        }

    # Prune entries in state that are no longer in .bib
    current_keys = {e.get("ID", "") for e in entries}
    for citekey in list(state.keys()):
        if citekey not in current_keys:
            logger.info(f"Entry removed from .bib, skipping: {citekey}")

    if not dry_run:
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"State saved ({len(state)} entries tracked)")

    return changed


def main():
    parser = argparse.ArgumentParser(description="Sync Zotero .bib to Obsidian LiteratureNotes")
    parser.add_argument("--bib", required=True, help="Path to Better BibTeX .bib export file")
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault root")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without writing files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    bib_path = Path(args.bib).expanduser().resolve()
    vault_path = Path(args.vault).expanduser().resolve()

    if not bib_path.exists():
        logger.error(f"Bib file not found: {bib_path}")
        sys.exit(1)

    changed = sync_notes(bib_path, vault_path, dry_run=args.dry_run)
    if changed:
        logger.info(f"Synced {len(changed)} note(s): {', '.join(sorted(changed))}")
    else:
        logger.info("No changes detected.")

    # Auto-commit to GitHub if running in a git repo
    token = load_env()
    if token and not args.dry_run:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=vault_path,
                capture_output=True,
                text=True,
            )
            if result.stdout.strip() == "true":
                subprocess.run(["git", "add", "LiteratureNotes/"], cwd=vault_path, check=False)
                subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    cwd=vault_path,
                    check=False,
                )
                # Only commit if there are changes
                diff = subprocess.run(
                    ["git", "diff", "--cached", "--stat"],
                    cwd=vault_path,
                    capture_output=True,
                    text=True,
                )
                if diff.stdout.strip():
                    subprocess.run(
                        ["git", "commit", "-m", f"sync: update literature notes ({len(changed)} changed)"],
                        cwd=vault_path,
                        check=False,
                    )
                    remote = subprocess.run(
                        ["git", "remote", "get-url", "origin"],
                        cwd=vault_path,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                    if remote.startswith("https://"):
                        remote = remote.replace("https://", f"https://{token}@")
                    subprocess.run(["git", "push", "origin", "HEAD"], cwd=vault_path, check=False)
                    logger.info("Changes pushed to GitHub.")
        except Exception as e:
            logger.warning(f"Git auto-push failed: {e}")


if __name__ == "__main__":
    main()

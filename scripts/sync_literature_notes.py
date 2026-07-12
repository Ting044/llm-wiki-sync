#!/usr/bin/env python3
"""
sync_literature_notes.py
=======================
Syncs Zotero literature notes from a Better BibTeX .bib export to an Obsidian vault.

Architecture:
  Zotero → BBT auto-export .bib → GitHub repo → This script → Obsidian vault (LiteratureNotes/)
  → Obsidian Sync → All devices

Learning-workflow guarantees:
  * Your own writing is NEVER overwritten. Each note has one machine-managed
    block between `<!-- sync:begin -->` / `<!-- sync:end -->`; everything
    outside it (your summary, questions, flashcards…) is left untouched.
  * Machine-managed frontmatter keys are updated from the .bib; every other
    key (status, read, rating, tags, anything you add) is preserved as-is.
  * Before an existing note is modified, a copy is saved to
    <vault>/.sync-backups/<timestamp>/ (last 10 runs kept).
  * New notes are created with a learning scaffold: one-sentence summary,
    key points, questions, links, and a flashcard section that works with
    the Obsidian Spaced Repetition plugin and exports to Anki
    (see scripts/export_anki_deck.py).
  * A Dataview reading dashboard (LiteratureNotes/00 阅读仪表盘.md) is
    created once if missing.

Usage:
  python3 sync_literature_notes.py --bib /path/to/library.bib --vault /path/to/vault

Requirements:
  pip install bibtexparser python-dotenv
"""

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import bibtexparser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Frontmatter keys owned by this script (rebuilt from .bib on every sync).
#    Every other key in an existing note is preserved verbatim. ───────────────
MACHINE_KEYS = [
    "type",
    "citekey",
    "title",
    "authors",
    "year",
    "date",
    "journal",
    "booktitle",
    "publisher",
    "doi",
    "url",
    "zotero_uri",
]

SYNC_BEGIN = "<!-- sync:begin"
SYNC_BEGIN_LINE = "<!-- sync:begin · 此区块由 llm-wiki-sync 自动维护,你的笔记请写在区块之外 -->"
SYNC_END = "<!-- sync:end -->"

DASHBOARD_NAME = "00 阅读仪表盘.md"
BACKUP_DIR_NAME = ".sync-backups"
BACKUP_KEEP_RUNS = 10


# ── helpers ───────────────────────────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    """Remove characters illegal in file names."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


def strip_latex(value: str) -> str:
    """Remove LaTeX braces and collapse whitespace."""
    value = re.sub(r"[{}]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def yaml_quote(value: str) -> str:
    """Safely quote a scalar for YAML frontmatter."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_bibtex(bib_path: Path) -> list[dict]:
    """Parse a BibTeX file and return a list of entry dicts."""
    content = bib_path.read_text(encoding="utf-8")
    if not content.strip():
        logger.warning(f"Bib file is empty: {bib_path}")
        return []

    bib_db = bibtexparser.loads(content)
    entries = []
    for entry in bib_db.entries:
        entry["ID"] = entry.get("ID", "")
        entry["ENTRYTYPE"] = entry.get("ENTRYTYPE", "article")
        entries.append(entry)
    return entries


def entry_hash(entry: dict) -> str:
    """Hash of every field that feeds the generated content."""
    key_fields = [
        "ID", "title", "author", "year", "date", "journal", "booktitle",
        "publisher", "doi", "url", "uri", "abstract",
    ]
    data = "|".join(str(entry.get(f, "")) for f in key_fields)
    return hashlib.sha256(data.encode()).hexdigest()[:12]


# ── generated content ─────────────────────────────────────────────────────────
def machine_frontmatter_lines(entry: dict) -> list[str]:
    """Frontmatter lines for the machine-owned keys, from a BibTeX entry."""
    lines = ["type: literature-note", f"citekey: {entry.get('ID', '')}"]

    title = strip_latex(entry.get("title", ""))
    if title:
        lines.append(f"title: {yaml_quote(title)}")

    authors = strip_latex(entry.get("author", "").replace("\n", " "))
    if authors:
        lines.append("authors:")
        for a in re.split(r"\s+and\s+", authors):
            lines.append(f"  - {yaml_quote(a.strip())}")

    year = entry.get("year", "").strip()
    entry_date = entry.get("date", year).strip()
    if year:
        lines.append(f"year: {year}")
    if entry_date:
        lines.append(f"date: {yaml_quote(entry_date)}")

    for field in ["journal", "booktitle", "publisher", "doi", "url"]:
        value = strip_latex(entry.get(field, ""))
        if value:
            lines.append(f"{field}: {yaml_quote(value)}")

    zotero_uri = entry.get("uri", "").strip()
    if zotero_uri and "zotero.org" in zotero_uri:
        lines.append(f"zotero_uri: {yaml_quote(zotero_uri)}")

    return lines


def default_user_frontmatter_lines() -> list[str]:
    """User-owned keys, written once at note creation and never touched again."""
    return [
        "status: unread",          # unread → reading → read
        f"added: {date.today().isoformat()}",
        "read:",                   # 读完时填日期,仪表盘用它排回顾队列
        "rating:",
        "tags: []",
    ]


def sync_block(entry: dict) -> str:
    """The machine-managed body block (citation info + abstract)."""
    lines = [SYNC_BEGIN_LINE, "", "## 文献信息", ""]

    authors = strip_latex(entry.get("author", "").replace("\n", " "))
    if authors:
        pretty = " · ".join(a.strip() for a in re.split(r"\s+and\s+", authors))
        lines.append(f"- **作者**:{pretty}")

    year = entry.get("year", "").strip()
    venue = strip_latex(entry.get("journal", "") or entry.get("booktitle", ""))
    if year or venue:
        lines.append(f"- **发表**:{year}{(' · ' + venue) if venue else ''}")

    doi = strip_latex(entry.get("doi", ""))
    if doi:
        lines.append(f"- **DOI**:[{doi}](https://doi.org/{doi})")

    url = entry.get("url", "").strip()
    if url:
        lines.append(f"- **链接**:{url}")

    zotero_uri = entry.get("uri", "").strip()
    if zotero_uri and "zotero.org" in zotero_uri:
        lines.append(f"- **Zotero**:[打开条目]({zotero_uri})")

    abstract = strip_latex(entry.get("abstract", ""))
    if abstract:
        lines += ["", "## 摘要", ""]
        lines += ["> " + l for l in abstract.splitlines() or [abstract]]

    lines += ["", SYNC_END]
    return "\n".join(lines)


LEARNING_SCAFFOLD = """
## 📌 一句话总结

%% 用自己的话,一句话说清这篇论文做了什么。写不出来 = 还没读懂(费曼检验) %%

## 🔑 关键要点

-

## ❓ 疑问与批判

-

## 🔗 关联笔记

-

## 📇 记忆卡片

#flashcards/文献

%% 一行一张卡,格式:问题::答案 (双冒号)。
   这些卡片可用 Obsidian Spaced Repetition 插件直接复习,
   也会由 export_anki_deck.py 自动打包成 Anki 牌组。 %%

"""


def new_note_content(entry: dict) -> str:
    fm = ["---"] + machine_frontmatter_lines(entry) + default_user_frontmatter_lines() + ["---"]
    return "\n".join(fm) + "\n\n" + sync_block(entry) + "\n" + LEARNING_SCAFFOLD


# ── merging into existing notes ───────────────────────────────────────────────
def split_frontmatter(text: str):
    """Return (frontmatter_items, body). Items = list of [key, raw_lines]."""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return None, text
    items, cur = [], None
    for line in m.group(1).split("\n"):
        km = re.match(r"^([A-Za-z_][\w-]*):(.*)$", line)
        if km:
            cur = [km.group(1), [line]]
            items.append(cur)
        elif cur is not None:
            cur[1].append(line)
    return items, m.group(2)


def merge_note(existing: str, entry: dict) -> str:
    """Update machine frontmatter + sync block; keep everything else verbatim."""
    items, body = split_frontmatter(existing)

    fm_lines = ["---"] + machine_frontmatter_lines(entry)
    if items is not None:
        for key, raw in items:
            if key not in MACHINE_KEYS:
                fm_lines += raw
    else:
        fm_lines += default_user_frontmatter_lines()
        body = existing  # no frontmatter found: keep whole file as body
    fm_lines.append("---")

    block = sync_block(entry)
    i = body.find(SYNC_BEGIN)
    j = body.find(SYNC_END, i) if i != -1 else -1
    if i != -1 and j != -1:
        new_body = body[:i] + block + body[j + len(SYNC_END):]
    else:
        # markers lost: prepend a fresh block, keep the user's body intact
        logger.warning(f"sync markers missing in note for {entry.get('ID')}; re-inserting block")
        new_body = block + "\n\n" + body.lstrip("\n")

    return "\n".join(fm_lines) + "\n\n" + new_body.lstrip("\n")


# ── backups ───────────────────────────────────────────────────────────────────
def backup_file(vault: Path, note_path: Path, run_stamp: str):
    dest_dir = vault / BACKUP_DIR_NAME / run_stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(note_path, dest_dir / note_path.name)


def prune_backups(vault: Path):
    root = vault / BACKUP_DIR_NAME
    if not root.exists():
        return
    runs = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda d: d.name)
    for old in runs[:-BACKUP_KEEP_RUNS]:
        shutil.rmtree(old, ignore_errors=True)


# ── reading dashboard ─────────────────────────────────────────────────────────
DASHBOARD = """---
type: dashboard
---

# 📖 阅读仪表盘

需要 [Dataview](https://blacksmithgu.github.io/obsidian-dataview/) 插件。
读的过程中维护两个字段:`status`(unread → reading → read)和读完日期 `read`。

## 📥 未读收件箱

```dataview
TABLE WITHOUT ID file.link AS 文献, authors AS 作者, year AS 年份, added AS 加入
FROM "LiteratureNotes"
WHERE type = "literature-note" AND status = "unread"
SORT added DESC
```

## 📖 正在读

```dataview
TABLE WITHOUT ID file.link AS 文献, authors AS 作者, year AS 年份
FROM "LiteratureNotes"
WHERE type = "literature-note" AND status = "reading"
```

## ⏳ 该回顾了(读完超过 30 天)

```dataview
TABLE WITHOUT ID file.link AS 文献, read AS 读完于
FROM "LiteratureNotes"
WHERE type = "literature-note" AND status = "read" AND read
  AND (date(today) - date(read)) >= dur(30 days)
SORT read ASC
```

## ✅ 最近读完

```dataview
TABLE WITHOUT ID file.link AS 文献, read AS 读完于, rating AS 评分
FROM "LiteratureNotes"
WHERE type = "literature-note" AND status = "read"
SORT read DESC
LIMIT 10
```

## 📊 统计

```dataview
TABLE WITHOUT ID status AS 状态, length(rows) AS 数量
FROM "LiteratureNotes"
WHERE type = "literature-note"
GROUP BY status
```
"""


# ── main sync ─────────────────────────────────────────────────────────────────
def sync_notes(bib_path: Path, vault_path: Path, dry_run: bool = False, backup: bool = True):
    vault = Path(vault_path).expanduser().resolve()
    notes_dir = vault / "LiteratureNotes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    state_file = vault / ".llm-wiki-sync-state.json"
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("State file unreadable, starting fresh")

    entries = parse_bibtex(bib_path)
    logger.info(f"Parsed {len(entries)} entries from {bib_path}")

    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    changed, created = [], []
    for entry in entries:
        citekey = sanitize_filename(entry.get("ID", "") or "unknown")
        note_path = notes_dir / f"{citekey}.md"
        new_hash = entry_hash(entry)

        if not note_path.exists():
            if dry_run:
                logger.info(f"[DRY-RUN] Would create: {note_path.name}")
            else:
                note_path.write_text(new_note_content(entry), encoding="utf-8")
                logger.info(f"Created: {note_path.name}")
            created.append(citekey)
        elif state.get(citekey, {}).get("hash") != new_hash:
            if dry_run:
                logger.info(f"[DRY-RUN] Would update sync block: {note_path.name}")
            else:
                if backup:
                    backup_file(vault, note_path, run_stamp)
                merged = merge_note(note_path.read_text(encoding="utf-8"), entry)
                note_path.write_text(merged, encoding="utf-8")
                logger.info(f"Updated (user content preserved): {note_path.name}")
            changed.append(citekey)

        state[citekey] = {
            "hash": new_hash,
            "path": str(note_path.relative_to(vault)),
            "synced_at": datetime.now().isoformat(),
        }

    # Entries removed from .bib: never delete the note (it holds your writing);
    # just report and drop from state.
    current_keys = {sanitize_filename(e.get("ID", "") or "unknown") for e in entries}
    for citekey in list(state.keys()):
        if citekey not in current_keys:
            logger.info(f"Entry no longer in .bib (note kept, untracked): {citekey}")
            del state[citekey]

    dashboard = notes_dir / DASHBOARD_NAME
    if not dashboard.exists() and not dry_run:
        dashboard.write_text(DASHBOARD, encoding="utf-8")
        logger.info(f"Created reading dashboard: {dashboard.name}")

    if not dry_run:
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"State saved ({len(state)} entries tracked)")
        if backup:
            prune_backups(vault)

    return created, changed


def main():
    parser = argparse.ArgumentParser(description="Sync Zotero .bib to Obsidian LiteratureNotes")
    parser.add_argument("--bib", required=True, help="Path to Better BibTeX .bib export file")
    parser.add_argument("--vault", required=True, help="Path to Obsidian vault root")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--no-backup", action="store_true", help="Skip per-run backups of modified notes")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    bib_path = Path(args.bib).expanduser().resolve()
    if not bib_path.exists():
        logger.error(f"Bib file not found: {bib_path}")
        sys.exit(1)

    created, changed = sync_notes(
        bib_path, Path(args.vault), dry_run=args.dry_run, backup=not args.no_backup
    )
    if created:
        logger.info(f"Created {len(created)} note(s): {', '.join(sorted(created))}")
    if changed:
        logger.info(f"Updated {len(changed)} note(s): {', '.join(sorted(changed))}")
    if not created and not changed:
        logger.info("No changes detected.")


if __name__ == "__main__":
    main()

# llm-wiki-sync

Zotero → Obsidian literature note sync pipeline.

## 知识星空 (Knowledge Sky)

`app/index.html` — a spaced-repetition learning app where every piece of
knowledge is a star in your night sky. Star brightness tracks real memory
retention (forgetting curve); reviewing at the right time makes stars
brighter and bigger; cards sharing a topic form constellations; stars due
for review pulse gold. SM-2 scheduling, localStorage persistence,
JSON export/import, fully offline — just open the file in a browser.

## How it works

```
Zotero (BBT auto-export)
    ↓ pushes .bib file
GitHub repo (this repo)
    ↓ triggers GitHub Actions
sync_literature_notes.py
    ↓ writes
Obsidian vault /LiteratureNotes/
    ↓ synced via Obsidian Sync
All your devices
```

## Setup

### 1. Better BibTeX auto-export

In Zotero → Better BibTeX preferences → Automatic Export:
- Format: `Better BibTeX`
- Run: `On change`
- Location: path to this repo's root folder

### 2. GitHub Actions

Push a `.bib` file to this repo to trigger the sync workflow automatically.

For manual/local runs:
```bash
python3 scripts/sync_literature_notes.py \
  --bib /path/to/library.bib \
  --vault /path/to/your/LLM-Wiki
```

### 3. Obsidian

The script writes markdown files to `LiteratureNotes/` in your vault with frontmatter:
- `type: literature-note`
- `citekey`, `title`, `authors`, `date`, `year`
- `journal`, `doi`, `url`, `zotero_uri`
- `abstract` (as body)

## Requirements

- Python 3.11+
- `pip install bibtexparser python-dotenv`

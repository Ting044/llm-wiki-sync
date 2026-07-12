# llm-wiki-sync

Zotero → Obsidian → Anki 学习工作流。

```
Zotero (BBT auto-export)
    ↓ pushes .bib file
GitHub repo (this repo)
    ↓ triggers GitHub Actions
sync_literature_notes.py   →  LiteratureNotes/<citekey>.md(带学习脚手架,永不覆盖你的笔记)
export_anki_deck.py        →  anki/LLM-Wiki.apkg(从笔记里的记忆卡片自动打包)
    ↓ Obsidian Sync / git
All your devices + Anki
```

## 核心保证

1. **你的笔记永不被覆盖。** 每篇文献笔记只有 `<!-- sync:begin -->` 到
   `<!-- sync:end -->` 之间的区块由脚本维护;区块之外的一切(总结、要点、
   疑问、记忆卡片)以及你自己的 frontmatter 字段(`status`、`read`、
   `rating`、`tags` 等)在每次同步中原样保留。
2. **改动前先备份。** 同步要修改已有笔记时,先把原文件复制到
   `<vault>/.sync-backups/<时间戳>/`(保留最近 10 次运行;git 历史是更长期的备份)。
3. **条目从 Zotero 删除时,笔记不会被删**,只是不再跟踪。

## 学习脚手架

新建的文献笔记自带以下结构(只在创建时写入一次):

- `status: unread → reading → read` + `read:` 读完日期 —— 驱动阅读仪表盘
- **📌 一句话总结**(费曼检验)/ **🔑 关键要点** / **❓ 疑问与批判** / **🔗 关联笔记**
- **📇 记忆卡片**:一行一张卡,`问题::答案`(单向)或 `问题:::答案`(双向)

## 阅读仪表盘

首次同步会在 `LiteratureNotes/00 阅读仪表盘.md` 生成一个
[Dataview](https://blacksmithgu.github.io/obsidian-dataview/) 仪表盘:
未读收件箱、正在读、**该回顾了(读完超过 30 天)**、最近读完、统计。
文件只生成一次,可自由改造。

## Anki 集成

`scripts/export_anki_deck.py` 扫描所有文献笔记的记忆卡片区块,打包成
`anki/LLM-Wiki.apkg`:

- 卡片语法与 Obsidian [Spaced Repetition](https://www.stephenmwangi.com/obsidian-spaced-repetition/)
  插件一致 —— 同一份卡片,Obsidian 里能复习,Anki 里也能复习。
- GUID 由 `citekey + 问题` 决定:重复导入 .apkg 会**原地更新**卡片,
  不产生重复,也不丢失你在 Anki 里的复习进度。
- 卡片背面自带来源链接(Zotero 条目)。
- GitHub Actions 每次同步后自动重新打包(内容没变则跳过),
  .apkg 会提交到仓库并作为 workflow artifact 上传,下载后双击导入 Anki 即可。

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
python3 scripts/export_anki_deck.py --vault /path/to/your/LLM-Wiki
```
Flags: `--dry-run`(预览)、`--no-backup`、`--force`(Anki 强制重新导出)。

### 3. Obsidian 推荐插件组合

- **Dataview**(必装):阅读仪表盘依赖它
- **Spaced Repetition**(可选):在 Obsidian 内直接复习 `#flashcards/文献` 卡片
- 不装任何插件,笔记和 Anki 导出也完全可用

## Frontmatter 字段

机器维护(每次同步更新):`type`, `citekey`, `title`, `authors`, `year`,
`date`, `journal`, `booktitle`, `publisher`, `doi`, `url`, `zotero_uri`。
摘要写在正文同步区块内(不再放 frontmatter,避免多行 YAML 问题)。

用户维护(创建时给默认值,之后不再触碰):`status`, `added`, `read`,
`rating`, `tags`,以及你自己添加的任何字段。

## Requirements

- Python 3.11+
- `pip install bibtexparser python-dotenv genanki`

## 历史版本

升级前的脚本与 workflow 备份在 `backups/2026-07-12-pre-learning-upgrade/`。
旧版行为差异:旧脚本在 bib 条目变动时会**整篇重写笔记**(用户内容会丢失),
且存在多个 YAML 转义 bug;旧版内置的 vault git 自动推送(依赖 `~/.hermes`
凭据)已移除,提交由 GitHub Actions 负责。

## 知识星空 (Knowledge Sky)

`app/index.html` — 一个单文件离线间隔重复应用:每个知识点是夜空中的一颗星,
亮度随真实遗忘曲线变化,同主题连成星座,到期的星泛金光。SM-2 调度、
localStorage 持久化、JSON 导入导出。直接用浏览器打开即可。

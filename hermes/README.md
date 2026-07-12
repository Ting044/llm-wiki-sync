# Hermes 整合:vet-study-coach

貼合你日常 Hermes + LLM-Wiki 學習場景的複習教練 skill。不是新 app,而是一個
可直接放進你 Hermes skills 目錄的組件——讓 vault 每晚**主動考你**,而不是你被動維護它。

## 設計依據(來自你的 USER.md / MEMORY.md)

- vault 保持乾淨、**不做 Anki 整合**(2026-05-12 定案)→ 複習狀態存
  `~/.hermes/state/study-coach/`,對 vault 只讀不寫
- **只接受自動化流程**、不手動同步 → 走 cron 每晚自動觸發
- **主動回憶**優於被動閱讀 → 先出題、等你答、再批改
- 考試用 Calendar 🔴 標記、動態追蹤走 Tasks → 考試倒數納入排程加權
- Telegram 官方格式(粗體 + • + ━━━━,不用表格)
- 交付前**自我驗證**(內建 self-test)

## 安裝

你的 hermes-repo 用 Obsidian Sync 而非 git,所以把這個資料夾複製進本機 skills 目錄即可:

```bash
cp -r hermes/skills/note-taking/vet-study-coach ~/.hermes/skills/note-taking/
python3 ~/.hermes/skills/note-taking/vet-study-coach/scripts/study_coach.py self-test
```

考試清單(可選,取不到會沿用舊檔、不阻斷複習):

```bash
mkdir -p ~/.hermes/state/study-coach
cat > ~/.hermes/state/study-coach/exams.json <<'JSON'
[{"subject":"parasitology","name":"獸醫寄生蟲學","date":"2026-07-16"}]
JSON
```

把 `SKILL.md` 末尾的 cron 片段加入 `cron/jobs.json` 即可每晚 21:00 自動開課。

詳細流程與指令見 `skills/note-taking/vet-study-coach/SKILL.md`。

---
name: vet-study-coach
category: note-taking
description: 每晚主動出題、批改、追進度的獸醫複習教練。從 LLM-Wiki 的 subjects/*/cards 挑卡,按 SM-2 到期時間 + 考試倒數加權排程,用主動回憶(先問後答)在 Telegram 出題,批改後更新記憶排程。觸發:「複習」「考我」「今晚讀什麼」「study coach」或每晚排程自動觸發。
triggers:
  - 複習 / 考我 / 今晚讀什麼
  - 考前衝刺
  - study coach
  - 每晚複習排程
---

# Vet Study Coach — 主動出題的複習教練

把「你被動維護 vault」翻轉成「vault 每晚主動考你」。所有排程與記憶狀態由
`scripts/study_coach.py`(確定性、可驗證)管理;LLM 只負責出題、批改、對話。

## 為什麼是這個形態

依據 MEMORY.md 既有決策,做了刻意取捨:

- **不動 vault、不整合 Anki**:複習狀態存在 `~/.hermes/state/study-coach/`,
  對 vault 只做唯讀 glob(與「LLM-Wiki 每月深度健檢」cron 的既有做法一致)。
  符合「Obsidian vault 保持乾淨、不做 Anki 整合」的定案。
- **主動回憶 + 間隔重複**:先出題、等你答、再給答案批改,而非給你看答案。
- **考試倒數加權**:考越近的科目卡片優先級越高(權重 `1 + 4·e^(-天數/7)`),
  貼合你「Calendar=🔴考試」的既有分類。
- **不用手動同步**:走 Hermes cron 每晚自動觸發(符合「只接受自動化流程」)。
- **Telegram 官方格式**:出題與週報用粗體 + • 鍵值對 + ━━━━ 分隔線,不用 Markdown 表格。

## 前提

- Vault:WSL `/mnt/c/Users/yitin/LLM-Wiki`,卡片位於 `subjects/{科目}/cards/**.md`
- 狀態目錄:`~/.hermes/state/study-coach/`
  - `state.json` — 每張卡的 SM-2 排程(腳本維護)
  - `exams.json` — 考試清單 `[{subject, name, date}]`,由 Hermes 從
    Google Tasks「📣 考試」清單刷新;取不到時沿用舊檔,不阻斷複習
- Telegram chat_id:`7587525783`

## 核心指令

```bash
PY=python3
COACH="$PY ~/.hermes/skills/note-taking/vet-study-coach/scripts/study_coach.py"

# 挑今晚要複習的卡(預設 8 張,考前科目優先)
$COACH pick --n 8

# 批改:傳入 [{path, grade}],grade = 0 忘了 / 1 模糊 / 2 記得 / 3 秒答
echo '[{"path":"subjects/parasitology/cards/日本血吸蟲.md","grade":2}]' | $COACH grade

# 各科待複習數 + 考試倒數 + 連續天數(週報用)
$COACH status

# 交付前自我驗證(MEMORY.md 要求:內建測試)
$COACH self-test
```

## 每晚複習流程(cron: `0 21 * * *`)

1. **挑卡**:`pick --n 8` 拿到 queue(每張含 subject、is_new、days_to_exam)。
   queue 為空 → 靜默結束,不發訊息。
2. **出題**:對 queue 逐一——用 Obsidian CLI 讀卡片內容
   (`"$OBS" vault=LLM-Wiki read path="..."`),依卡片正文生成一道**主動回憶題**,
   一次發一題到 Telegram,等使用者作答。
   - 出題只問「觸發回憶」的問題(例:「日本血吸蟲的中間宿主是?其蟲卵側棘特徵?」),
     不要直接貼出答案。
3. **批改**:使用者答完,對照卡片內容給簡短回饋(對/錯/補充),並判定 grade 0–3。
4. **寫回**:把整輪 `[{path, grade}]` 用 `grade` 指令寫回,更新排程與連續天數。
5. **收尾**:發一則 Telegram 總結(見下方格式),含本輪張數、連續天數、明日到期數。

## 週日晚間週報(cron: `0 20 * * 0`)

跑 `status`,把各科進度、最近考試倒數、本週複習數、連續天數整理成 Telegram 訊息。
任一科目「考試 ≤ 7 天且待複習 > 10」時,追加一行 `⚠️ 衝刺提醒`。

## Telegram 訊息格式(官方格式,勿用表格)

```
**🌙 今晚複習完成**

• 複習張數:8（記得 5 / 模糊 2 / 忘了 1）
• 連續天數:12 天 🔥
• 明日到期:6 張
• 最近考試:寄生蟲學 還有 5 天

━━━━━━━━━━━━━━

忘了的卡半天後會再考你，模糊的明天見。
```

## 排程註冊(加入 cron/jobs.json)

```json
{
  "name": "獸醫複習教練（每晚）",
  "prompt": "load skill vet-study-coach，執行每晚複習流程：pick → 逐題主動回憶 → 批改 → grade 寫回 → Telegram 總結。queue 為空則靜默結束。",
  "skills": ["vet-study-coach", "obsidian"],
  "schedule": {"kind": "cron", "expr": "0 21 * * *"},
  "deliver": "origin",
  "origin": {"platform": "telegram", "chat_id": "7587525783"}
}
```

## 驗證標準(交付前必跑)

`study_coach.py self-test` 覆蓋:vault 掃描、考前科目排序、考試倒數計算、
批改後排程更新、已複習卡不重複、忘了→半天重來、間隔遞增、status 統計。
**全部通過才算交付**(符合 MEMORY.md 的 self-validation 要求)。

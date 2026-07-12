#!/usr/bin/env python3
"""
study_coach.py — vet-study-coach 的排程核心(確定性部分)
=========================================================
LLM 負責出題、批改、對話;本腳本負責可驗證的調度與狀態:

  pick    挑出今晚要複習的卡片(SM-2 到期 + 考試倒數加權),輸出 JSON
  grade   寫回複習評分,更新每張卡的記憶排程
  status  各科目待複習數量、考試倒數、連續天數(週報用)
  self-test  內建單元測試(交付驗證標準)

狀態檔:~/.hermes/state/study-coach/state.json(絕不寫入 vault)
考試檔:~/.hermes/state/study-coach/exams.json(由 Hermes 從 Google
        Tasks「📣 考試」清單刷新;無法取得時沿用舊檔)

Vault 只做唯讀 glob(與月度深度健檢 cron 的既有做法一致);
所有 vault 寫入操作一律不在本腳本職責內。
"""

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DAY = 86400
VAULT_DEFAULT = "/mnt/c/Users/yitin/LLM-Wiki"
STATE_DIR_DEFAULT = Path.home() / ".hermes" / "state" / "study-coach"

# SM-2 lite:grade 0 忘了 / 1 模糊 / 2 記得 / 3 秒答
GRADE_LABELS = {0: "忘了", 1: "模糊", 2: "記得", 3: "秒答"}


# ── state ─────────────────────────────────────────────────────────────────────
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def empty_state():
    return {"version": 1, "cards": {}, "sessions": []}


# ── vault scan(唯讀)──────────────────────────────────────────────────────────
def scan_cards(vault: Path) -> list[dict]:
    """列出 subjects/*/cards/**.md,回傳 [{path, subject, name}]。"""
    out = []
    subjects_dir = vault / "subjects"
    if not subjects_dir.exists():
        return out
    for card in sorted(subjects_dir.glob("*/cards/**/*.md")):
        rel = card.relative_to(vault)
        out.append({
            "path": str(rel),
            "subject": rel.parts[1],
            "name": card.stem,
        })
    return out


# ── scheduling ────────────────────────────────────────────────────────────────
def exam_weight(subject: str, exams: list[dict], today: date) -> tuple[float, int | None]:
    """考試越近權重越高:1 + 4·exp(-天數/7)。回傳 (weight, days_to_exam)。"""
    best = None
    for e in exams:
        if e.get("subject") != subject:
            continue
        try:
            d = (date.fromisoformat(str(e["date"])) - today).days
        except Exception:
            continue
        if d >= 0 and (best is None or d < best):
            best = d
    if best is None:
        return 1.0, None
    return 1.0 + 4.0 * math.exp(-best / 7.0), best


def card_priority(meta: dict, weight: float, now_ts: float) -> float:
    """到期越久、考試越近,優先級越高;新卡有固定基礎分。"""
    due = meta.get("due", 0)
    if meta.get("reps", 0) == 0:
        return 1.0 * weight                      # 新卡
    overdue_days = max(0.0, (now_ts - due) / DAY)
    return (2.0 + min(overdue_days, 14.0)) * weight  # 到期卡優先於新卡


def pick(vault: Path, state: dict, exams: list[dict], n: int, today: date, now_ts: float) -> dict:
    cards = scan_cards(vault)
    known = state["cards"]
    weights, countdown = {}, {}
    for c in cards:
        if c["subject"] not in weights:
            w, d = exam_weight(c["subject"], exams, today)
            weights[c["subject"]] = w
            countdown[c["subject"]] = d

    scored = []
    for c in cards:
        meta = known.get(c["path"], {})
        is_due = meta.get("reps", 0) > 0 and meta.get("due", 0) <= now_ts
        is_new = meta.get("reps", 0) == 0
        if not (is_due or is_new):
            continue
        scored.append((card_priority(meta, weights[c["subject"]], now_ts), is_new, c, meta))

    scored.sort(key=lambda t: (-t[0], t[2]["path"]))

    # 新卡最多佔 30%,避免一晚全是生面孔;但到期卡不足以填滿時,
    # 允許新卡補上剩餘名額(冷啟動 / 全新科目)。
    due_available = sum(1 for _, is_new, _, _ in scored if not is_new)
    max_new = max(1, round(n * 0.3), n - due_available)
    queue, new_taken = [], 0
    for _, is_new, c, meta in scored:
        if len(queue) >= n:
            break
        if is_new:
            if new_taken >= max_new:
                continue
            new_taken += 1
        queue.append({
            **c,
            "is_new": is_new,
            "reps": meta.get("reps", 0),
            "days_to_exam": countdown[c["subject"]],
        })

    return {
        "date": today.isoformat(),
        "total_cards": len(cards),
        "due_or_new": len(scored),
        "queue": queue,
        "exam_countdown": {s: d for s, d in countdown.items() if d is not None},
    }


def apply_grade(meta: dict, grade: int, now_ts: float) -> dict:
    ease = meta.get("ease", 2.5)
    interval = meta.get("interval", 0.0)
    reps = meta.get("reps", 0)
    lapses = meta.get("lapses", 0)

    if grade == 0:
        interval, ease, lapses = 0.5, max(1.3, ease - 0.2), lapses + 1
    elif grade == 1:
        interval, ease = max(1.0, interval * 1.2), max(1.3, ease - 0.15)
    elif grade == 2:
        interval = 1.0 if interval < 1 else interval * ease
    else:
        interval = 3.0 if interval < 1 else interval * ease * 1.3
        ease = min(3.2, ease + 0.15)

    return {
        "ease": round(ease, 2),
        "interval": round(interval, 2),
        "reps": reps + 1,
        "lapses": lapses,
        "last": now_ts,
        "due": now_ts + interval * DAY,
    }


def grade_session(state: dict, results: list[dict], now_ts: float, today: date) -> dict:
    graded = 0
    for r in results:
        path, g = r.get("path"), r.get("grade")
        if path is None or g not in (0, 1, 2, 3):
            continue
        state["cards"][path] = {**state["cards"].get(path, {}), **apply_grade(state["cards"].get(path, {}), g, now_ts)}
        graded += 1
    state["sessions"].append({"date": today.isoformat(), "graded": graded})
    state["sessions"] = state["sessions"][-90:]
    return {"graded": graded, "streak": streak(state, today)}


def streak(state: dict, today: date) -> int:
    days = {s["date"] for s in state["sessions"] if s.get("graded", 0) > 0}
    n, d = 0, today
    while d.isoformat() in days:
        n, d = n + 1, d - timedelta(days=1)
    return n


def status(vault: Path, state: dict, exams: list[dict], today: date, now_ts: float) -> dict:
    cards = scan_cards(vault)
    per = {}
    for c in cards:
        s = per.setdefault(c["subject"], {"total": 0, "new": 0, "due": 0, "learned": 0})
        meta = state["cards"].get(c["path"], {})
        s["total"] += 1
        if meta.get("reps", 0) == 0:
            s["new"] += 1
        else:
            s["learned"] += 1
            if meta.get("due", 0) <= now_ts:
                s["due"] += 1
    for sub in per:
        _, d = exam_weight(sub, exams, today)
        per[sub]["days_to_exam"] = d
    week_ago = (today - timedelta(days=7)).isoformat()
    return {
        "date": today.isoformat(),
        "subjects": per,
        "streak": streak(state, today),
        "reviews_this_week": sum(s["graded"] for s in state["sessions"] if s["date"] >= week_ago),
    }


# ── self-test ─────────────────────────────────────────────────────────────────
def self_test() -> int:
    import tempfile
    fails = []

    def check(name, cond):
        (print(f"  ✅ {name}") if cond else fails.append(name)) if cond else print(f"  ❌ {name}")

    with tempfile.TemporaryDirectory() as td:
        vault = Path(td)
        for sub, names in {"parasitology": ["日本血吸蟲", "犬蛔蟲", "貓絛蟲"], "histology": ["上皮組織"]}.items():
            d = vault / "subjects" / sub / "cards"
            d.mkdir(parents=True)
            for n in names:
                (d / f"{n}.md").write_text("# " + n, encoding="utf-8")

        today = date(2026, 5, 14)
        now_ts = datetime(2026, 5, 14, 21, 0).timestamp()
        exams = [{"subject": "parasitology", "name": "獸醫寄生蟲學", "date": "2026-05-19"}]
        state = empty_state()

        r = pick(vault, state, exams, n=10, today=today, now_ts=now_ts)
        check("掃到全部 4 張卡", r["total_cards"] == 4)
        check("考前科目排在最前", r["queue"][0]["subject"] == "parasitology")
        check("考試倒數 = 5 天", r["exam_countdown"].get("parasitology") == 5)

        res = [{"path": c["path"], "grade": 2} for c in r["queue"][:3]]
        g = grade_session(state, res, now_ts, today)
        check("批改 3 張", g["graded"] == 3)
        check("連續天數 = 1", g["streak"] == 1)

        r2 = pick(vault, state, exams, n=10, today=today, now_ts=now_ts + 60)
        check("剛複習的卡不再出現", all(q["path"] not in {x["path"] for x in res} for q in r2["queue"]))

        m = apply_grade({}, 0, now_ts)
        check("忘了 → 半天後重來", m["interval"] == 0.5 and m["lapses"] == 1)
        m2 = apply_grade(apply_grade({}, 2, now_ts), 2, now_ts)
        check("記得×2 → 間隔拉長", m2["interval"] > 1)

        st = status(vault, state, exams, today, now_ts)
        check("status 統計正確", st["subjects"]["parasitology"]["learned"] == 3)

    print(f"\n{'❌ FAIL: ' + ', '.join(fails) if fails else '✅ self-test 全部通過'}")
    return 1 if fails else 0


# ── cli ───────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="vet-study-coach scheduling core")
    p.add_argument("command", choices=["pick", "grade", "status", "self-test"])
    p.add_argument("--vault", default=VAULT_DEFAULT)
    p.add_argument("--state-dir", default=str(STATE_DIR_DEFAULT))
    p.add_argument("--n", type=int, default=8, help="pick:本次複習張數")
    p.add_argument("--results", help="grade:JSON 檔路徑,格式 [{path, grade}];省略則讀 stdin")
    args = p.parse_args()

    if args.command == "self-test":
        sys.exit(self_test())

    state_dir = Path(args.state_dir)
    state_file = state_dir / "state.json"
    exams_file = state_dir / "exams.json"
    vault = Path(args.vault)
    state = load_json(state_file, empty_state())
    exams = load_json(exams_file, [])
    today, now_ts = date.today(), datetime.now().timestamp()

    if args.command == "pick":
        print(json.dumps(pick(vault, state, exams, args.n, today, now_ts), ensure_ascii=False, indent=2))
    elif args.command == "grade":
        raw = Path(args.results).read_text(encoding="utf-8") if args.results else sys.stdin.read()
        out = grade_session(state, json.loads(raw), now_ts, today)
        save_json(state_file, state)
        print(json.dumps(out, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(status(vault, state, exams, today, now_ts), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

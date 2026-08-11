"""③ 撰写层：按 日 / 周 / 月 / 年 从 events.csv 生成双语简报骨架到 briefings/。

数据层（上方各维度分组 + 信源对照表）由流水线每次自动重生成。
周/月/年简报额外预留一个 `## AI 深度解析` 插槽：该标题之后的内容由维护者或 AI
手写，流水线重生成时**保留不覆盖**。写作提纲见 templates/{weekly,monthly,yearly}.md。
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import datetime, timedelta, timezone

from utils import BRIEF, MASTER, TYPE_LABELS, read_events, load_config, log


def fmt_row(r: dict) -> str:
    rel = r.get("reliability", "")
    conf = r.get("confidence", "")
    disc = " ⚠分歧" if str(r.get("disagreement_flag", "")).lower().startswith("y") else ""
    return (f"- **{r.get('title_zh', '')}** / {r.get('title_en', '')}  "
            f"｜ 可靠{rel} 置信{conf} 来源方:{r.get('source_side', '')}{disc}\n"
            f"  - 中：{r.get('summary_zh', '')}\n"
            f"  - EN：{r.get('summary_en', '')}")


# 深度解析插槽的哨兵标题：流水线在重生成数据层时，会保留该标题之后的全部内容。
ANALYSIS_SENTINEL = "## AI 深度解析"


def build_range(rows_all, start: str, end: str, out_path, header_lines: list[str],
                analysis_slot: bool = False, period: str | None = None) -> None:
    rows = [r for r in rows_all if start <= (r.get("date") or "") <= end]
    parts = list(header_lines)
    for t, (zh, en) in TYPE_LABELS.items():
        grp = [r for r in rows if r.get("event_type") == t]
        if not grp:
            continue
        parts.append(f"\n## {zh} / {en}\n")
        for r in grp:
            parts.append(fmt_row(r) + "\n")
    disc = [r for r in rows if str(r.get("disagreement_flag", "")).lower().startswith("y")]
    if disc:
        parts.append("\n## 信源对照 / Source Cross-check\n")
        parts.append("| 维度 | 乌 | 俄 | 第三方 | 分歧点 |\n"
                     "|------|----|----|--------|--------|\n")
        for r in disc:
            parts.append(
                f"| {r.get('title_zh', '')} | {r.get('source_ua', '')} | "
                f"{r.get('source_ru', '')} | {r.get('source_third', '')} | "
                f"{r.get('disagreement_note_zh', '')} |\n")
    if analysis_slot:
        # 保留人工/AI 撰写的深度解析层，不被自动重生成覆盖
        kept = ""
        if out_path.exists():
            existing = out_path.read_text(encoding="utf-8")
            idx = existing.find(ANALYSIS_SENTINEL)
            if idx != -1:
                kept = existing[idx:]
        if not kept:
            tpl = f"templates/{period}.md" if period else "templates/"
            kept = (
                f"\n{ANALYSIS_SENTINEL} / AI Deep Analysis\n\n"
                f"_以下由维护者或 AI 基于上方数据撰写；流水线每次重生成都会**保留本段**，不会被覆盖。_\n"
                f"_写作提纲与可直接粘贴的提示词见 `{tpl}`。_\n\n")
        parts.append("\n" + kept)
    else:
        parts.append("\n---\n*本简报由自动化流水线生成骨架，叙述由维护者定稿。原始数据见 `data/master/events.csv`。*\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(parts), encoding="utf-8")
    log(f"briefing -> {out_path} ({len(rows)} events)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--week", action="store_true")
    ap.add_argument("--month", action="store_true")
    ap.add_argument("--year", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    editor = cfg.get("editor", "system")
    rows = read_events()

    if args.week:
        d = datetime.strptime(args.date, "%Y-%m-%d").date()
        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
        y, w, _ = d.isocalendar()
        out = BRIEF / "weekly" / f"{y}-W{w:02d}.md"
        header = [
            f"# 俄乌战争周复盘 · {y} 第 {w:02d} 周\n",
            f"> **编号** W-{y}{w:02d} ｜ **编辑** {editor}\n",
        ]
        build_range(rows, str(monday), str(sunday), out, header,
                    analysis_slot=True, period="weekly")
        return

    if args.month:
        y, m = (int(x) for x in args.date.split("-")[:2])
        last = monthrange(y, m)[1]
        out = BRIEF / "monthly" / f"{y}-{m:02d}.md"
        header = [
            f"# 俄乌战争月度深度 · {y}-{m:02d}\n",
            f"> **编号** M-{y}{m:02d} ｜ **编辑** {editor}\n",
        ]
        build_range(rows, f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last}", out, header,
                    analysis_slot=True, period="monthly")
        return

    if args.year:
        y = int(args.date.split("-")[0])
        out = BRIEF / "yearly" / f"{y}.md"
        header = [
            f"# 俄乌战争年度评估 · {y}\n",
            f"> **编号** Y-{y} ｜ **编辑** {editor} ｜ **数据基线** `data/master/events.csv`\n",
        ]
        build_range(rows, f"{y}-01-01", f"{y}-12-31", out, header,
                    analysis_slot=True, period="yearly")
        return

    # 默认：每日快讯
    target = args.date
    out = BRIEF / "daily" / f"{target}.md"
    header = [
        f"# 俄乌战争每日快讯 · {target}\n",
        f"> **编号** D-{target.replace('-', '')} ｜ **编辑** {editor} ｜ **数据基线** `data/master/events.csv`\n",
        "> **免责声明**：非官方、开源、中立汇编；数据可能滞后或有误，仅供参考。\n",
    ]
    build_range(rows, target, target, out, header)


if __name__ == "__main__":
    main()

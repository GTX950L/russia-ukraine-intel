"""④ 校验层：CI 质量闸。发现违规返回退出码 1（阻断提交）。

校验规则（与 references/confidence_rubric.md 一致）：
- 必填字段非空：event_id/date/theater/event_type/title_zh/title_en/reliability/confidence
- theater / event_type 必须在受控词表内
- reliability ∈ A–F；confidence ∈ 1–6
- disagreement_flag=yes 必须有 disagreement_note_zh
- 高置信(confidence≤2) 必须至少带一个可核实来源(URL 或第三方源名)
"""
from __future__ import annotations

import sys

from utils import MASTER, read_events, load_vocab, log

REQUIRED = ["event_id", "date", "theater", "event_type",
            "title_zh", "title_en", "reliability", "confidence"]


def main() -> int:
    vocab = load_vocab()
    valid_theaters = set(vocab["theaters"])
    valid_types = set(vocab["event_types"])
    rel_set = set(vocab["reliability_levels"])

    rows = read_events()
    if not rows:
        log("events.csv 为空 —— 允许引导期空库")
        return 0

    errors: list[str] = []
    for i, r in enumerate(rows, 1):
        rid = r.get("event_id") or f"row{i}"
        for fld in REQUIRED:
            if not str(r.get(fld, "")).strip():
                errors.append(f"{rid}: 缺必填字段 {fld}")
        if r.get("theater") not in valid_theaters:
            errors.append(f"{rid}: theater 非法 '{r.get('theater')}'")
        if r.get("event_type") not in valid_types:
            errors.append(f"{rid}: event_type 非法 '{r.get('event_type')}'")
        if str(r.get("reliability", "")) not in rel_set:
            errors.append(f"{rid}: reliability 非法 '{r.get('reliability')}'")
        conf_ok = True
        try:
            c = int(r.get("confidence", 0))
            if not (1 <= c <= 6):
                errors.append(f"{rid}: confidence 超出 1-6")
                conf_ok = False
        except (ValueError, TypeError):
            errors.append(f"{rid}: confidence 非整数 '{r.get('confidence')}'")
            conf_ok = False
            c = 0
        if str(r.get("disagreement_flag", "")).lower().startswith("y") \
                and not str(r.get("disagreement_note_zh", "")).strip():
            errors.append(f"{rid}: 标记分歧但缺 disagreement_note_zh")
        if conf_ok and c <= 2:
            has_source = any(str(r.get(k, "")).strip() for k in
                             ("url_ua", "url_ru", "url_third", "source_third"))
            if not has_source:
                errors.append(f"{rid}: 高置信(≤2)但无任何可核实来源")

    if errors:
        for e in errors:
            log("ERROR " + e)
        log(f"validate FAILED: {len(errors)} 个问题")
        return 1
    log(f"validate OK: {len(rows)} 行全部合规")
    return 0


if __name__ == "__main__":
    sys.exit(main())

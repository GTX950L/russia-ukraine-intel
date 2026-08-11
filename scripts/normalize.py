"""② 解析层：合并 data/raw（适配器） + data/seed（同 schema 手工补录） → events.csv。

- 受控词表约束（theater / event_type 非法则回落到默认值）。
- 按内容指纹去重，避免重复写入。
- 缺 event_id 的行自动编号；缺字段填 config 默认值。
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone

from utils import (DATA, MASTER, RAW, SEED, SCHEMA_VERSION, load_vocab,
                   read_events, write_events, new_event_id, row_hash, log)

VALID_DEFAULTS = {"theater": "political", "event_type": "external"}


def parse_raw_viina(path) -> list[dict]:
    """VIINA 事件 CSV → 本项目 schema（best-effort 映射子集）。"""
    out = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                out.append({
                    "date": (r.get("date") or "")[:10],
                    "theater": "political",
                    "event_type": "civilian",
                    "title_en": r.get("sub_event_type") or r.get("event_type") or "",
                    "summary_en": r.get("notes") or "",
                    "source_side": "third",
                    "source_third": "VIINA",
                    "reliability": "B",
                    "confidence": "3",
                    "disagreement_flag": "no",
                    "forecast_related": "no",
                    "tags": "viina",
                    "editor": "pipeline",
                })
    except Exception as e:  # noqa: BLE001
        log(f"viina parse failed: {e}")
    return out


def parse_raw_generic_csv(path, source_name) -> list[dict]:
    out = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                out.append({
                    "date": (r.get("date") or "")[:10],
                    "theater": r.get("theater") or "political",
                    "event_type": r.get("event_type") or "external",
                    "title_en": r.get("title_en") or r.get("title") or "",
                    "summary_en": r.get("summary_en") or r.get("summary") or "",
                    "source_side": "third",
                    "source_third": source_name,
                    "reliability": "B",
                    "confidence": "3",
                    "disagreement_flag": "no",
                    "forecast_related": "no",
                    "tags": "auto",
                    "editor": "pipeline",
                })
    except Exception as e:  # noqa: BLE001
        log(f"generic_csv parse failed: {e}")
    return out


def main() -> None:
    vocab = load_vocab()
    valid_theaters = set(vocab["theaters"])
    valid_types = set(vocab["event_types"])

    existing = read_events()
    seen = {row_hash(r) for r in existing}
    used_ids = {r.get("event_id") for r in existing}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seq = max([int(r["event_id"].split("-")[-1])
               for r in existing if r.get("event_id", "").startswith(today + "-")] + [0])

    merged = list(existing)
    added = 0

    def ingest(r: dict) -> None:
        nonlocal added, seq
        # 词表约束
        if r.get("theater") not in valid_theaters:
            r["theater"] = VALID_DEFAULTS["theater"]
        if r.get("event_type") not in valid_types:
            r["event_type"] = VALID_DEFAULTS["event_type"]
        if row_hash(r) in seen:
            return
        seen.add(row_hash(r))
        if not r.get("event_id") or r.get("event_id") in used_ids:
            seq += 1
            r["event_id"] = new_event_id(r.get("date") or today, seq)
            used_ids.add(r["event_id"])
        r.setdefault("schema_version", SCHEMA_VERSION)
        r.setdefault("updated_at", today)
        r.setdefault("editor", "pipeline")
        r.setdefault("reliability", "C")
        r.setdefault("confidence", "3")
        r.setdefault("disagreement_flag", "no")
        r.setdefault("forecast_related", "no")
        r.setdefault("source_side", "third")
        merged.append(r)
        added += 1

    # raw 适配器
    if RAW.exists():
        for p in sorted(RAW.glob("*.csv")):
            name = p.name
            if "viina" in name.lower():
                for r in parse_raw_viina(p):
                    ingest(r)
            else:
                for r in parse_raw_generic_csv(p, name):
                    ingest(r)

    # seed（同 schema 手工补录）
    if SEED.exists():
        for p in sorted(SEED.glob("*.csv")):
            with p.open(encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    r["schema_version"] = r.get("schema_version") or SCHEMA_VERSION
                    ingest(r)

    write_events(merged)
    log(f"normalize done: {len(merged)} total, +{added} new")


if __name__ == "__main__":
    main()

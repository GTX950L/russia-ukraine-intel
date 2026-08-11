"""② 解析层：合并 data/raw（适配器） + data/seed（同 schema 手工补录） → events.csv。

- 受控词表约束（theater / event_type 非法则回落到默认值）。
- 按内容指纹去重，避免重复写入。
- 缺 event_id 的行自动编号；缺字段填 config 默认值。
- 适配器按文件名/扩展名分发：viina(.zip) / petro(.json) / 其他(.csv 通用)。
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from utils import (DATA, MASTER, RAW, SEED, SCHEMA_VERSION, load_vocab,
                   read_events, write_events, new_event_id, row_hash, log)

VALID_DEFAULTS = {"theater": "political", "event_type": "external"}


def _find_col(cols, *candidates) -> str | None:
    """在表头里按候选名子串匹配，返回首个命中的列名。"""
    for c in candidates:
        for col in cols:
            if col and c.lower() in col.lower():
                return col
    return None


# VIINA event_type（英文）→ 本项目受控 event_type
VIINA_EVENT_MAP = {
    "battle": "frontline", "shell": "frontline", "assault": "frontline", "ground": "frontline",
    "strike": "frontline", "missile": "frontline", "drone": "frontline", "bomb": "frontline",
    "air": "frontline", "artiller": "frontline",
    "protest": "civilian", "demonstrat": "civilian", "arrest": "civilian",
    "detain": "civilian", "civilian": "civilian",
    "diplom": "diplomacy", "negoti": "diplomacy", "mediat": "diplomacy", "talk": "diplomacy",
    "sanction": "economy", "econom": "economy",
    "cyber": "cyber",
    "nuclear": "deterrence", "strategic": "deterrence",
    "mobil": "troops", "troop": "troops", "recruit": "troops",
}
# 地名关键词 → 本项目受控 theater
VIINA_THEATER_MAP = {
    "avdiivka": "east-avdiivka", "bakhmut": "east-bakhmut", "donetsk": "east-donetsk",
    "luhansk": "east-luhansk", "kherson": "south-kherson", "zaporizhzhia": "south-zaporizhzhia",
    "crimea": "south-crimea", "kharkiv": "north-kharkiv", "kursk": "border-kursk",
    "black sea": "black-sea", "odesa": "black-sea", "odessa": "black-sea",
    "kyiv": "homeland-ua", "kiev": "homeland-ua",
    "moscow": "homeland-ru",
}


def parse_viina_zip(path) -> list[dict]:
    """VIINA 事件 zip（内含 CSV，Git LFS）→ 本项目 schema。

    列名随上游变化，故采用灵活映射：先记录真实列名到日志，再按关键词映射
    event_type / theater；原文 notes 原样保留。标题中英暂置英文（标 needs-zh），
    待人工/AI 翻译。
    """
    out = []
    try:
        z = zipfile.ZipFile(path)
        csvname = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
        if not csvname:
            log("viina: zip 内无 CSV，跳过")
            return out
        with z.open(csvname) as f:
            text = f.read().decode("utf-8-sig", "replace")
        reader = csv.DictReader(io.StringIO(text))
        cols = reader.fieldnames or []
        log("VIINA columns: " + ",".join(cols))
        c_date = _find_col(cols, "event_date", "date")
        c_et = _find_col(cols, "event_type")
        c_sub = _find_col(cols, "sub_event_type")
        c_notes = _find_col(cols, "notes", "description", "summary")
        c_src = _find_col(cols, "source")
        c_loc = _find_col(cols, "location", "admin1", "admin2", "admin3", "admin")
        for r in reader:
            date = (r.get(c_date) or "")[:10] if c_date else ""
            if not date:
                continue
            et_raw = (r.get(c_et) or "").strip()
            sub = (r.get(c_sub) or "").strip()
            notes = (r.get(c_notes) or "").strip()
            src = (r.get(c_src) or "").strip()
            loc = (r.get(c_loc) or "").strip()
            et_mapped = "external"
            low = et_raw.lower()
            for k, v in VIINA_EVENT_MAP.items():
                if k in low:
                    et_mapped = v
                    break
            theater = "political"
            lowloc = (loc + " " + et_raw).lower()
            for k, v in VIINA_THEATER_MAP.items():
                if k in lowloc:
                    theater = v
                    break
            title_en = (et_raw + " " + loc).strip() or (notes[:60] if notes else "VIINA event")
            tags = ["viina", "needs-zh"]
            if src:
                tags.append("media:" + src[:20])
            if et_raw:
                tags.append("viina_type:" + et_raw[:20])
            if sub:
                tags.append("sub:" + sub[:20])
            out.append({
                "date": date, "theater": theater, "event_type": et_mapped,
                "title_zh": title_en, "title_en": title_en,
                "summary_zh": notes, "summary_en": notes,
                "source_side": "third", "source_ua": "", "source_ru": "", "source_third": "VIINA",
                "url_ua": "", "url_ru": "", "url_third": "",
                "reliability": "B", "confidence": "3",
                "disagreement_flag": "no", "disagreement_note_zh": "",
                "forecast_related": "no", "tags": ";".join(tags), "editor": "pipeline",
            })
    except Exception as e:  # noqa: BLE001
        log(f"viina zip parse failed: {e}")
    return out


def parse_petro_json(path) -> list[dict]:
    """PetroIvaniuk 俄方装备累计损失 JSON → 本项目 schema（取最新一日）。"""
    out = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data:
            return out
        last = data[-1]
        date = last.get("date", "")
        if not date:
            return out
        cats = {k: v for k, v in last.items() if k not in ("date", "day")}
        top = list(cats.items())[:10]
        zh = "俄方装备累计损失（截至" + date + "）：" + "; ".join(f"{k}={v}" for k, v in top)
        en = "Cumulative Russian equipment losses (as of " + date + "): " + "; ".join(
            f"{k}={v}" for k, v in top)
        out.append({
            "date": date, "theater": "homeland-ru", "event_type": "equipment",
            "title_zh": f"俄方装备损失更新（{date}）",
            "title_en": f"Russian equipment losses update ({date})",
            "summary_zh": zh, "summary_en": en,
            "source_side": "third", "source_ua": "", "source_ru": "",
            "source_third": "PetroIvaniuk(基于Oryx)",
            "url_ua": "", "url_ru": "",
            "url_third": "https://github.com/PetroIvaniuk/2022-Ukraine-Russia-War-Dataset",
            "reliability": "B", "confidence": "3",
            "disagreement_flag": "no", "disagreement_note_zh": "",
            "forecast_related": "no",
            "tags": "equipment-loss;petroivaniuk;oryx;cumulative", "editor": "pipeline",
        })
    except Exception as e:  # noqa: BLE001
        log(f"petro json parse failed: {e}")
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

    # raw 适配器（按文件名/扩展名分发）
    if RAW.exists():
        for p in sorted(RAW.glob("*")):
            name = p.name.lower()
            try:
                if "viina" in name and p.suffix == ".zip":
                    for r in parse_viina_zip(p):
                        ingest(r)
                elif "petro" in name and p.suffix == ".json":
                    for r in parse_petro_json(p):
                        ingest(r)
                elif p.suffix == ".csv":
                    for r in parse_raw_generic_csv(p, p.name):
                        ingest(r)
            except Exception as e:  # noqa: BLE001
                log(f"raw ingest failed {p.name}: {e}")

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

"""② 解析层：合并 data/raw（按 config 的 parser 分发）→ events.csv。

设计要点：
- 单一可信源：所有事件从 data/raw 的受控解析器产出，再合并 data/seed 手工补录。
- 解析器由 config.yaml 的 `parser:` 字段驱动（config-driven dispatch），
  新增信源只需在 config 加一项 + 在 PARSERS 注册函数。
- 受控词表约束（theater / event_type 非法则回落到默认值）。
- 按内容指纹去重，避免重复写入。
- 每个解析器都防御式：异常仅 log，不抛出、不阻断流水线。

新增源（本次）：deepstate(geojson 快照) / isw(战报摘要) / oryx(Atom feed) /
ua_mod(乌防部损失数字) / ru_mod(俄防部简报)。全部 best-effort。
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from utils import (DATA, MASTER, RAW, SEED, SCHEMA_VERSION, load_config,
                   load_vocab, read_events, write_events, new_event_id,
                   row_hash, log)

try:
    from bs4 import BeautifulSoup
except ImportError:  # CI 缺包时降级，HTML 解析器会跳过
    BeautifulSoup = None  # type: ignore[assignment]

VALID_DEFAULTS = {"theater": "political", "event_type": "external"}

# 乌语月份 -> 数字（用于解析乌防部损失日期）
UA_MONTHS = {
    "січня": "01", "лютого": "02", "березня": "03", "квітня": "04",
    "травня": "05", "червня": "06", "липня": "07", "серпня": "08",
    "вересня": "09", "жовтня": "10", "листопада": "11", "грудня": "12",
}


def _find_col(cols, *candidates) -> str | None:
    """在表头里按候选名子串匹配，返回首个命中的列名。"""
    for c in candidates:
        for col in cols:
            if col and c.lower() in col.lower():
                return col
    return None


# ──────────────────────────────────────────────────────────────────────────
# 既有适配器：VIINA / PetroIvaniuk
# ──────────────────────────────────────────────────────────────────────────
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
VIINA_THEATER_MAP = {
    "avdiivka": "east-avdiivka", "bakhmut": "east-bakhmut", "donetsk": "east-donetsk",
    "luhansk": "east-luhansk", "kherson": "south-kherson", "zaporizhzhia": "south-zaporizhzhia",
    "crimea": "south-crimea", "kharkiv": "north-kharkiv", "kursk": "border-kursk",
    "black sea": "black-sea", "odesa": "black-sea", "odessa": "black-sea",
    "kyiv": "homeland-ua", "kiev": "homeland-ua",
    "moscow": "homeland-ru",
}


def parse_viina_zip(path: Path) -> list[dict]:
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


def parse_petro_json(path: Path) -> list[dict]:
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


# ──────────────────────────────────────────────────────────────────────────
# 新增适配器
# ──────────────────────────────────────────────────────────────────────────
def parse_deepstate_geojson(path: Path) -> list[dict]:
    """DeepState 控制区/前线 GeoJSON → 快照事件（兼作地图图层资产）。

    社区镜像每日更新；实测为单 feature / 空属性（前线或控制区多边形）。
    仅记录『快照已更新』+ 几何概要，不直接声称控制变化（避免误导）。
    """
    out = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        feats = data.get("features", [])
        m = re.search(r"(\d{8})", path.name)
        date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}" if m else ""
        geom_types = sorted({f.get("geometry", {}).get("type") for f in feats if f.get("geometry")})
        named = [f.get("properties", {}) for f in feats if f.get("properties")]
        summary = (f"DeepState 控制区/前线快照（{date or '当日'}）：{len(feats)} 个要素，"
                   f"几何类型 {', '.join(geom_types) or 'n/a'}。")
        if named:
            items = []
            for p in named[:8]:
                nm = p.get("name") or p.get("title")
                st = p.get("status") or p.get("owner")
                if nm:
                    items.append(f"{nm}" + (f"({st})" if st else ""))
            if items:
                summary += " 区域：" + "; ".join(items)
        out.append({
            "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "theater": "political", "event_type": "external",
            "title_zh": f"DeepState 战线控制快照（{date or '当日'}）",
            "title_en": f"DeepState front-line control snapshot ({date or 'today'})",
            "summary_zh": summary, "summary_en": summary,
            "source_side": "third", "source_ua": "", "source_ru": "", "source_third": "DeepStateMap",
            "url_ua": "", "url_ru": "", "url_third": "https://deepstatemap.org",
            "reliability": "B", "confidence": "3",
            "disagreement_flag": "no", "disagreement_note_zh": "",
            "forecast_related": "no",
            "tags": "deepstate;control-snapshot;frontline-map", "editor": "pipeline",
        })
    except Exception as e:  # noqa: BLE001
        log(f"deepstate parse failed: {e}")
    return out


def parse_isw_html(path: Path) -> list[dict]:
    """ISW 每日战报：RSS 被 403，改抓产品页抽取最新战报标题/链接（仅摘要）。

    诚实标注：自动抽取标题与链接，正文分析需人工/AI 复核（manual-verify）。
    """
    out = []
    if BeautifulSoup is None:
        log("isw: bs4 缺失，跳过"); return out
    try:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        cand = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "campaign-assessment" in href or "/backgrounder/" in href:
                txt = a.get_text(strip=True)
                if txt and len(txt) > 10:
                    cand = (href, txt)
                    break
        if not cand:
            log("isw: 未找到战报链接，跳过")
            return out
        href, txt = cand
        if href.startswith("/"):
            href = "https://www.understandingwar.org" + href
        date = ""
        mtag = soup.find("meta", {"property": "article:published_time"})
        if mtag and mtag.get("content"):
            date = mtag["content"][:10]
        if not date:
            dm = re.search(r"(\d{4}-\d{2}-\d{2})", txt)
            if dm:
                date = dm.group(1)
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "date": date, "theater": "political", "event_type": "external",
            "title_zh": f"ISW 每日战报：{txt[:80]}",
            "title_en": f"ISW daily assessment: {txt[:80]}",
            "summary_zh": (f"ISW 发布《俄罗斯攻势战役评估》（{date}）。原文：{href}"
                           f"（自动抽取标题，正文分析建议人工/AI 复核）"),
            "summary_en": (f"ISW published Russian Offensive Campaign Assessment ({date}). "
                           f"URL: {href} (title auto-extracted; full analysis needs review)."),
            "source_side": "third", "source_ua": "", "source_ru": "", "source_third": "ISW",
            "url_ua": "", "url_ru": "", "url_third": href,
            "reliability": "A", "confidence": "3",
            "disagreement_flag": "no", "disagreement_note_zh": "",
            "forecast_related": "no",
            "tags": "isw;daily-report;summary-only;manual-verify", "editor": "pipeline",
        })
    except Exception as e:  # noqa: BLE001
        log(f"isw parse failed: {e}")
    return out


def parse_oryx_feed(path: Path) -> list[dict]:
    """Oryx Blogspot Atom feed → 最新发布事件的标题/日期/链接。

    Oryx 主清单为超长文、难自动计数；这里只抽取『最新发布』信号，明细需人工核对。
    """
    out = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
        entries = [el for el in root.iter() if el.tag.endswith("entry") or el.tag.endswith("item")]
        if not entries:
            log("oryx: feed 无 entry，跳过")
            return out
        e = entries[0]
        title = published = link = ""
        for child in e.iter():
            t = child.tag.split("}")[-1]
            if t == "title" and not title:
                title = (child.text or "").strip()
            elif t in ("published", "updated") and not published:
                published = (child.text or "").strip()
            elif t == "link" and not link:
                href = child.get("href")
                if href:
                    link = href
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", published)
        date = dm.group(1) if dm else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not title:
            log("oryx: 无标题，跳过")
            return out
        out.append({
            "date": date, "theater": "political", "event_type": "equipment",
            "title_zh": f"Oryx 最新发布：{title[:80]}",
            "title_en": f"Oryx latest: {title[:80]}",
            "summary_zh": (f"Oryx 发布装备损失相关更新（{date}）：{title}。原文：{link}"
                           f"（自动抽取标题，明细需人工核对）"),
            "summary_en": (f"Oryx published equipment-loss update ({date}): {title}. "
                           f"URL: {link} (title auto-extracted; details need manual verification)."),
            "source_side": "third", "source_ua": "", "source_ru": "", "source_third": "Oryx",
            "url_ua": "", "url_ru": "", "url_third": link,
            "reliability": "A", "confidence": "2",
            "disagreement_flag": "no", "disagreement_note_zh": "",
            "forecast_related": "no",
            "tags": "oryx;feed;manual-verify", "editor": "pipeline",
        })
    except Exception as e:  # noqa: BLE001
        log(f"oryx parse failed: {e}")
    return out


def parse_ua_mod_html(path: Path) -> list[dict]:
    """乌克兰国防部首页 → 结构化单日损失数字（人员/坦克/火炮/无人机等）。

    与俄方宣称天然形成『双方对照』。官方自报，reliability C / confidence 2。
    """
    out = []
    if BeautifulSoup is None:
        log("ua_mod: bs4 缺失，跳过"); return out
    try:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        text = soup.get_text("\n")
        dm = re.search(r"Бойові втрати ворога на\s*(\d+)\s*([а-яіїєґ]+)\s*(\d{4})", text)
        date = ""
        if dm:
            d = int(dm.group(1))
            mon = UA_MONTHS.get(dm.group(2).lower())
            y = int(dm.group(3))
            if mon:
                date = f"{y}-{mon}-{d:02d}"
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pairs = [
            ("Особовий склад", "personnel"), ("Танки", "tanks"),
            ("Бойові машини", "afv"), ("Артилерійські системи", "artillery"),
            ("БПЛА", "uav"), ("Літаки", "aircraft"), ("Гелікоптери", "helicopters"),
            ("Кораблі", "ships"), ("Крилаті ракети", "cruise_missiles"),
        ]
        found = {}
        for label, _ in pairs:
            m = re.search(re.escape(label) + r"\s*[\n\r]+?\s*([\d\s\u00a0]+)", text)
            if m:
                val = re.sub(r"\D", "", m.group(1))  # 仅保留数字（去掉空格/换行/窄空格）
                if val:
                    found[label] = int(val)
        if not found:
            log("ua_mod: 未找到损失数字，跳过")
            return out
        zh = "乌方通报俄军单日损失（" + date + "）：" + "；".join(
            f"{k}={v}" for k, v in found.items())
        en = "UA MoD reports RU losses (" + date + "): " + "; ".join(
            f"{k}={v}" for k, v in found.items())
        out.append({
            "date": date, "theater": "homeland-ru", "event_type": "equipment",
            "title_zh": f"乌国防部通报俄军单日装备/人员损失（{date}）",
            "title_en": f"UA MoD reports daily RU losses ({date})",
            "summary_zh": zh, "summary_en": en,
            "source_side": "ua", "source_ua": "乌克兰国防部", "source_ru": "", "source_third": "",
            "url_ua": "https://www.mil.gov.ua/", "url_ru": "", "url_third": "",
            "reliability": "C", "confidence": "2",
            "disagreement_flag": "no", "disagreement_note_zh": "",
            "forecast_related": "no",
            "tags": "ua-mod;losses;official-claim", "editor": "pipeline",
        })
    except Exception as e:  # noqa: BLE001
        log(f"ua_mod parse failed: {e}")
    return out


def parse_ru_mod_html(path: Path) -> list[dict]:
    """俄罗斯国防部每日简报：best-effort（eng.mil.ru 可能从境外不可达）。

    失败仅日志不阻断；成功也仅抽取标题+首段，标注 manual-verify。
    """
    out = []
    if BeautifulSoup is None:
        log("ru_mod: bs4 缺失，跳过"); return out
    try:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        body = next((p for p in paras if len(p) > 60), "")
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "date": date, "theater": "political", "event_type": "external",
            "title_zh": f"俄国防部每日简报（自动抽取，需人工核实）：{title[:60]}",
            "title_en": f"RU MoD daily briefing (auto, verify): {title[:60]}",
            "summary_zh": (body[:300] if body else "（未能抽取正文，建议人工核对俄防部官网 eng.mil.ru）"),
            "summary_en": (body[:300] if body else "(body not extracted; verify RU MoD site manually)"),
            "source_side": "ru", "source_ua": "", "source_ru": "俄罗斯国防部", "source_third": "",
            "url_ua": "", "url_ru": "https://eng.mil.ru/", "url_third": "",
            "reliability": "C", "confidence": "3",
            "disagreement_flag": "no", "disagreement_note_zh": "",
            "forecast_related": "no",
            "tags": "ru-mod;briefing;manual-verify", "editor": "pipeline",
        })
    except Exception as e:  # noqa: BLE001
        log(f"ru_mod parse failed: {e}")
    return out


# 解析器注册表（config.parser -> 函数）
PARSERS = {
    "viina": parse_viina_zip,
    "petro_equipment": parse_petro_json,
    "deepstate": parse_deepstate_geojson,
    "isw": parse_isw_html,
    "oryx": parse_oryx_feed,
    "ua_mod": parse_ua_mod_html,
    "ru_mod": parse_ru_mod_html,
}


def main() -> None:
    cfg = load_config()
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

    # raw 适配器（按 config.parser 分发）
    raw_files = {p.name: p for p in (RAW.glob("*") if RAW.exists() else [])}
    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        name = src.get("name", "")
        parser = PARSERS.get(src.get("parser"))
        if not parser:
            log(f"no parser registered for {name}; skip")
            continue
        key = next((fn for fn in raw_files if fn.lower().startswith(name.lower())), None)
        if not key:
            log(f"no raw file for {name}; skip")
            continue
        try:
            for r in parser(raw_files[key]):
                ingest(r)
        except Exception as e:  # noqa: BLE001
            log(f"parse {name} failed: {e}")

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

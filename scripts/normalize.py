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
from datetime import datetime, timedelta, timezone
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
# VIINA 实际 schema（event_1pd_latest_YYYY.zip）：
#   - 事件类型以 t_* 布尔列表示（'1'/'0'），无 event_type 列；
#   - 地点在 ADM1_NAME（如 "Donets'k"、'Kharkiv'、'Crimea'）；
#   - 行动方以 a_rus_b / a_ukr_b / a_civ_b 表示；
#   - date 为 YYYYMMDD。
# 旧适配器按子串匹配不存在的 event_type/location 列，导致 2.6 万行全被标成
# external+political。下面按真实 schema 重映射。
# 优先级从高到低：取首个为真的 t_* 标志作为主 event_type。
VIINA_TYPE_FLAGS = [
    ("t_cyber_b", "cyber"),
    ("t_civcas_b", "civilian"), ("t_hospital_b", "civilian"),
    ("t_arrest_b", "civilian"), ("t_property_b", "civilian"),
    ("t_milcas_b", "troops"),
    ("t_san_b", "economy"),
    ("t_airstrike_b", "frontline"), ("t_artillery_b", "frontline"),
    ("t_armor_b", "frontline"), ("t_firefight_b", "frontline"),
    ("t_control_b", "frontline"), ("t_retreat_b", "frontline"),
    ("t_occupy_b", "frontline"), ("t_raid_b", "frontline"),
    ("t_loc_b", "frontline"), ("t_aad_b", "frontline"),
    ("t_ied_b", "frontline"), ("t_mil_b", "frontline"),
]
# ADM1_NAME（去标点后）子串 -> 受控战区
VIINA_THEATER_MAP = {
    "donetsk": "east-donetsk", "luhansk": "east-luhansk",
    "kharkiv": "north-kharkiv", "kherson": "south-kherson",
    "zaporizhzhia": "south-zaporizhzhia", "crimea": "south-crimea",
    "krym": "south-crimea", "odesa": "black-sea", "odessa": "black-sea",
    "kyiv": "homeland-ua", "kiev": "homeland-ua",
    "moscow": "homeland-ru", "kursk": "border-kursk",
    "bakhmut": "east-bakhmut", "avdiivka": "east-avdiivka",
}
VIINA_RECENT_DAYS = 30  # 仅纳入近 N 天，避免历史全量回填撑爆 master


def _is_true(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "t", "y", "yes")


def parse_viina_zip(path: Path, recent_days: int = VIINA_RECENT_DAYS) -> list[dict]:
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
        c_date = _find_col(cols, "date")
        c_adm1 = _find_col(cols, "adm1_name", "geonameid")
        c_asc = _find_col(cols, "asciiname")
        c_src = _find_col(cols, "sources")
        if not c_date:
            log("viina: 无 date 列，跳过")
            return out
        cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=recent_days)).strftime("%Y-%m-%d")
        added = 0
        for r in reader:
            raw_date = (r.get(c_date) or "").strip()
            if len(raw_date) == 8 and raw_date.isdigit():
                date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            else:
                date = ""
            if not date or date < cutoff:
                continue
            # 主事件类型：取首个为真的 t_* 标志
            et_mapped = "external"
            for flag, et in VIINA_TYPE_FLAGS:
                if _is_true(r.get(flag, "")):
                    et_mapped = et
                    break
            loc = (r.get(c_adm1) or "").strip()
            theater = "political"
            lowloc = re.sub(r"[^a-z]", "", loc.lower())  # 去掉撇号/空格便于匹配
            for k, v in VIINA_THEATER_MAP.items():
                if k in lowloc:
                    theater = v
                    break
            # 行动方标签（VIINA 为第三方聚合，source_side 仍是 third）
            actors = []
            if _is_true(r.get("a_rus_b", "")):
                actors.append("actor:ru")
            if _is_true(r.get("a_ukr_b", "")):
                actors.append("actor:ua")
            if _is_true(r.get("a_civ_b", "")):
                actors.append("actor:civ")
            tags = ["viina"] + actors
            src = (r.get(c_src) or "").strip()
            if src:
                tags.append("media:" + src[:30])
            for flag, et in VIINA_TYPE_FLAGS:  # 记录所有为真的类型，便于检索
                if _is_true(r.get(flag, "")):
                    tags.append("viina_t:" + et)
            place = (r.get(c_asc) or loc or "n/a").strip()  # 用定居点名提高去重粒度
            title_en = f"{place}: {et_mapped} event"
            notes = (f"VIINA 事件（{date}）：地点 {place}，主类型 {et_mapped}"
                      + (f"，信源 {src}" if src else ""))
            out.append({
                "date": date, "theater": theater, "event_type": et_mapped,
                "title_zh": title_en, "title_en": title_en,
                "summary_zh": notes, "summary_en": notes,
                "source_side": "third", "source_ua": "", "source_ru": "", "source_third": "VIINA",
                "url_ua": "", "url_ru": "",
                "url_third": "https://github.com/zhukovyuri/VIINA",
                "reliability": "B", "confidence": "3",
                "disagreement_flag": "no", "disagreement_note_zh": "",
                "forecast_related": "no", "tags": ";".join(tags), "editor": "pipeline",
            })
            added += 1
        log(f"viina: 解析 {added} 条（近 {recent_days} 天）")
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
            "date": date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
            "theater": "political", "event_type": "frontline",
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
            date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
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
    注意：feeds/posts/default 是全站 feed（会混入叙利亚等无关战区文章），
    必须用关键词过滤掉与俄乌无关的条目。
    """
    # 标题命中任一关键词才算与俄乌相关
    RU_UA_KEYWORDS = (
        "ukraine", "russia", "ukrainian", "russian", "donbas", "donetsk", "luhansk",
        "kherson", "zaporizhzhia", "kharkiv", "crimea", "kursk", "odessa", "odesa",
        "t-72", "t-80", "t-90", "t-64", "bmp", "btr", "mt-lb", "ka-52", "su-25",
        "su-34", "su-35", "mig-31", "lancet", "shahed", "geran", "tornado-s",
        "tank", "artillery", "armored", "armoured", "equipment loss", "destroyed",
        "vehicle", "wagner", "azov", "armed forces", "ministry of defence",
    )
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
        if not title:
            log("oryx: 无标题，跳过")
            return out
        if not any(k in title.lower() for k in RU_UA_KEYWORDS):
            log(f"oryx: 标题与俄乌无关，跳过: {title[:60]}")
            return out
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", published)
        date = dm.group(1) if dm else datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
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
            date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
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
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
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


# ──────────────────────────────────────────────────────────────────────────
# 通用新闻首页抽取（UA/RU 可达信源；best-effort，失败仅日志不阻断）
# ──────────────────────────────────────────────────────────────────────────
NEWS_UA_RU_KEYWORDS = (
    "ukraine", "ukrainian", "russia", "russian", "donbas", "donetsk", "luhansk",
    "kherson", "zaporizhzhia", "kharkiv", "crimea", "kursk", "odessa", "odesa",
    "kyiv", "kiev", "putin", "zelensky", "zelenskyy", "moscow", "росс", "украин",
    "киев", "крым", "пути", "зеленск", "всу", "вооруженн", "спецопер",
)


def _extract_news_headlines(path: Path, base_url: str, max_n: int = 10,
                            require_ukraine: bool = False) -> list[tuple[str, str]]:
    """从新闻首页抽取头条（锚文本+链接），去重取前 max_n 条。"""
    if BeautifulSoup is None:
        log(f"news: bs4 缺失，跳过 {path.name}")
        return []
    out = []
    try:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            txt = a.get_text(" ", strip=True)
            if not txt or len(txt) < 25 or len(txt) > 140:
                continue
            if not re.search(r"/\d{6,}", href):  # 需像文章（含数字 id）
                continue
            if href in seen:
                continue
            seen.add(href)
            if href.startswith("/"):
                href = base_url + href
            if require_ukraine and not any(k in txt.lower() for k in NEWS_UA_RU_KEYWORDS):
                continue
            out.append((txt, href))
            if len(out) >= max_n:
                break
    except Exception as e:  # noqa: BLE001
        log(f"news extract failed ({path.name}): {e}")
    return out


def _news_row(txt: str, href: str, side: str, src_name: str, url_field: str) -> dict:
    date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    row = {
        "date": date, "theater": "political", "event_type": "external",
        "title_zh": txt, "title_en": txt,
        "summary_zh": f"{src_name} 头条：{txt}", "summary_en": f"{src_name} headline: {txt}",
        "source_side": side, "source_ua": "", "source_ru": "", "source_third": "",
        "url_ua": "", "url_ru": "", "url_third": "",
        "reliability": "C", "confidence": "3",
        "disagreement_flag": "no", "disagreement_note_zh": "",
        "forecast_related": "no", "editor": "pipeline",
    }
    row[url_field] = href
    if side == "ua":
        row["source_ua"] = src_name
        row["tags"] = "ukrinform;ua-news;manual-verify"
    else:
        row["source_ru"] = src_name
        row["tags"] = "ria;ru-news;manual-verify"
    return row


def parse_ua_ukrinform_html(path: Path) -> list[dict]:
    """Ukrinform（乌方国家通讯社，可达）：抽取当期乌战头条，作 UA 侧信源。"""
    out = []
    for txt, href in _extract_news_headlines(path, "https://www.ukrinform.net", max_n=10):
        out.append(_news_row(txt, href, "ua", "Ukrinform", "url_ua"))
    log(f"ukrinform: {len(out)} 条")
    return out


def parse_ru_ria_html(path: Path) -> list[dict]:
    """RIA Novosti（俄方国家通讯社，可达）：仅取与乌战相关头条，作 RU 侧信源。"""
    out = []
    for txt, href in _extract_news_headlines(path, "https://ria.ru", max_n=10,
                                             require_ukraine=True):
        out.append(_news_row(txt, href, "ru", "RIA Novosti", "url_ru"))
    log(f"ria: {len(out)} 条（乌战相关）")
    return out


# 解析器注册表（config.parser -> 函数）；置于所有解析器定义之后。
PARSERS = {
    "viina": parse_viina_zip,
    "petro_equipment": parse_petro_json,
    "deepstate": parse_deepstate_geojson,
    "isw": parse_isw_html,
    "oryx": parse_oryx_feed,
    "ua_mod": parse_ua_mod_html,
    "ru_mod": parse_ru_mod_html,
    "ua_ukrinform": parse_ua_ukrinform_html,
    "ru_ria": parse_ru_ria_html,
}


def main() -> None:
    cfg = load_config()
    vocab = load_vocab()
    valid_theaters = set(vocab["theaters"])
    valid_types = set(vocab["event_types"])

    existing = read_events()
    seen = {row_hash(r) for r in existing}
    used_ids = {r.get("event_id") for r in existing}
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    # 序号基线取全局最大（跨日期递增），避免不同日期前缀的事件撞号
    seq = 0
    for r in existing:
        m = re.match(r"^.*-(\d+)$", r.get("event_id", ""))
        if m:
            try:
                seq = max(seq, int(m.group(1)))
            except ValueError:
                pass

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
            # 冲突避让：循环递增直到生成一个未占用的 id
            while True:
                seq += 1
                cand = new_event_id(r.get("date") or today, seq)
                if cand not in used_ids:
                    break
            r["event_id"] = cand
            used_ids.add(cand)
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

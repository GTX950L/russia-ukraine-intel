"""⑤ 渲染层：读 events.csv → 生成 docs/ 站点（仪表盘 + 简报渲染页 + 归档页）。

采用 GitHub Pages "Deploy from branch: main / docs" 模式（仓库根 .nojekyll 关闭 Jekyll）。
站点为纯静态：前端用内嵌 EVENTS 做客户端筛选，无需后端。
额外生成：
- docs/briefings.html         全部简报归档页
- docs/briefings/<组>/<名>.html  每份简报的独立渲染页（md → html）
- 首页顶部"今日最新情报"区块（自动展示最新一份每日简报）
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils import DOCS, MASTER, RAW, ROOT, THEATER_ZH, TYPE_LABELS, read_events, load_config, log, BRIEF

# ---------------------------------------------------------------------------
# 轻量 markdown → html（覆盖本项目简报模板：标题/引用/列表/表格/粗斜体/代码/裸链接）
# ---------------------------------------------------------------------------

_URL = r"https?://[^\s<>()（）]+[^\s<>().,;:!?\"'（）]"


def _inline(s: str) -> str:
    """行内元素：**粗**、*斜*、_斜_、`代码`、[文字](链接)、裸 URL。"""
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<i>\1</i>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((" + _URL + r")\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r'(?<!["=])(' + _URL + r")", r'<a href="\1">\1</a>', s)
    return s


def md_to_html(md: str) -> str:
    """块级解析：标题/引用/表格/分隔线/列表（嵌套用缩进呈现）/段落。"""
    lines = md.replace("\r\n", "\n").split("\n")
    html: list[str] = []
    in_list = False
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            if in_list:
                html.append("</ul>")
                in_list = False
            lvl = len(m.group(1))
            html.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if re.match(r"^-{3,}$", s):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append("<hr>")
            i += 1
            continue
        if s.startswith(">"):
            if in_list:
                html.append("</ul>")
                in_list = False
            q = []
            while i < n and lines[i].strip().startswith(">"):
                q.append(_inline(lines[i].strip()[1:].strip()))
                i += 1
            html.append("<blockquote>" + "<br>".join(q) + "</blockquote>")
            continue
        if s.startswith("|"):
            if in_list:
                html.append("</ul>")
                in_list = False
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip().strip("|"))
                i += 1
            body = [r for r in rows if not re.match(r"^[\s:\-|]+$", r)]
            if body:
                tbl = ["<table>"]
                for idx, r in enumerate(body):
                    tag = "th" if idx == 0 else "td"
                    cells = "".join(f"<{tag}>{_inline(c.strip())}</{tag}>" for c in r.split("|"))
                    tbl.append(f"<tr>{cells}</tr>")
                tbl.append("</table>")
                html.append("".join(tbl))
            continue
        m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                html.append("<ul>")
                in_list = True
            level = len(m.group(1)) // 2
            indent = f' style="margin-left:{level}em"' if level else ""
            html.append(f"<li{indent}>{_inline(m.group(2))}</li>")
            i += 1
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        para: list[str] = []
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|>|[-*]\s|\s*[-*]\s|\||-{3,})", lines[i]):
            para.append(_inline(lines[i].strip()))
            i += 1
        html.append("<p>" + "<br>".join(para) + "</p>")
    if in_list:
        html.append("</ul>")
    return "\n".join(html)


# ---------------------------------------------------------------------------
# 页面模板（浅色主题）
# ---------------------------------------------------------------------------

CSS = """\
  :root { --bg:#fff; --fg:#1a1a1a; --mut:#666; --bd:#e3e3e3; --acc:#185fa5; }
  * { box-sizing:border-box; }
  body { font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; margin:0; color:var(--fg); background:var(--bg); }
  header { padding:28px 20px 10px; border-bottom:1px solid var(--bd); }
  h1 { margin:0 0 4px; font-size:22px; }
  .sub { color:var(--mut); font-size:13px; }
  .sub a { color:var(--acc); text-decoration:none; }
  .wrap { max-width:1080px; margin:0 auto; padding:18px 20px 60px; }
  .stats { display:flex; gap:12px; flex-wrap:wrap; margin:16px 0; }
  .card { flex:1 1 140px; border:1px solid var(--bd); border-radius:12px; padding:14px; text-align:center; }
  .card .num { font-size:26px; font-weight:600; color:var(--acc); }
  .card .lbl { font-size:12px; color:var(--mut); margin-top:4px; }
  .filters { display:flex; gap:10px; flex-wrap:wrap; margin:10px 0 16px; }
  input,select { padding:8px 10px; border:1px solid var(--bd); border-radius:8px; font-size:13px; }
  input { flex:1 1 240px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--bd); vertical-align:top; }
  th { background:#fafafa; position:sticky; top:0; }
  .tag { display:inline-block; background:#eef3fb; color:var(--acc); border-radius:6px; padding:1px 7px; font-size:11px; margin-right:4px; }
  .disc { color:#b3401b; font-weight:600; }
  footer { color:var(--mut); font-size:12px; border-top:1px solid var(--bd); margin-top:30px; padding-top:14px; }
  a { color:var(--acc); }
  .latest { border:1px solid var(--bd); border-radius:12px; margin:16px 0; }
  .lh { display:flex; align-items:center; gap:10px; padding:12px 16px; border-bottom:1px solid var(--bd); flex-wrap:wrap; }
  .lh h2 { margin:0; font-size:16px; }
  .lmeta { color:var(--mut); font-size:12px; }
  .lbtn { font-size:12px; border:1px solid var(--bd); border-radius:8px; padding:4px 10px; text-decoration:none; color:var(--acc); background:#fafafa; }
  .lbtn:hover { background:#eef3fb; }
  .lb { padding:6px 18px 14px; max-height:480px; overflow:auto; font-size:13px; line-height:1.65; }
  .lb h1 { font-size:17px; margin:10px 0 6px; }
  .lb h2 { font-size:15px; margin:14px 0 6px; }
  .lb h3 { font-size:14px; margin:10px 0 4px; }
  .lb blockquote { margin:8px 0; padding:6px 12px; background:#fafafa; border-left:3px solid var(--acc); color:var(--mut); font-size:12px; }
  .lb ul { margin:6px 0; padding-left:22px; }
  .lb table { font-size:12px; margin:8px 0; }
  .lb hr { border:none; border-top:1px dashed var(--bd); margin:12px 0; }
  .lb code { background:#f2f2f2; border-radius:4px; padding:1px 5px; font-size:12px; }
  .lb a { word-break:break-all; }
  .lb p { margin:8px 0; }
  .archive section { margin:18px 0; }
  .archive h2 { font-size:15px; border-bottom:1px solid var(--bd); padding-bottom:6px; }
  .archive ul { list-style:none; padding:0; margin:8px 0; }
  .archive li { padding:6px 0; border-bottom:1px dashed #eee; font-size:13px; }
  .archive li a { text-decoration:none; }
  .archive .d { color:var(--mut); font-size:12px; margin-left:8px; }
"""

INDEX_HEAD = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<style>%s</style>
</head>
<body>
<header><h1>%s</h1><div class="sub">中英双语 · 乌俄与第三方信源交叉对照 · NATO 可信度分级 ｜ 更新：%s</div></header>
<div class="wrap">
  %s
  <div class="stats">%s</div>
  <div class="filters">
    <input id="q" placeholder="搜索关键词 / search...">
    <select id="fType"><option value="">全部维度</option></select>
    <select id="fTheater"><option value="">全部战区</option></select>
  </div>
  <table>
    <thead><tr><th>日期</th><th>战区</th><th>维度</th><th>事件（中/EN）</th><th>可靠</th><th>置信</th><th>来源方</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  <footer>
    非官方、开源、中立汇编，数据可能滞后或有误，仅供参考。原始数据：<a href="events.json">events.json</a>
    ｜ 简报：<a href="briefings.html">全部简报</a> ｜ 今日最新：<a href="%s">最新简报</a>
    ｜ 态势地图：<a href="map.html">战场地图</a>
    ｜ 方法论：<a href="https://github.com/GTX950L/russia-ukraine-intel/tree/main/references">references/</a>
  </footer>
</div>
<script>
const EVENTS = %s;
const TYPE_ZH = %s;
const THEATER_ZH = %s;
const tbody = document.getElementById('tbody');
const q = document.getElementById('q');
const fType = document.getElementById('fType');
const fTheater = document.getElementById('fTheater');
function uniq(a){ return [...new Set(a)].filter(Boolean); }
uniq(EVENTS.map(e=>e.event_type)).forEach(t=>{ const o=document.createElement('option'); o.value=t; o.textContent=(TYPE_ZH[t]||t); fType.appendChild(o); });
uniq(EVENTS.map(e=>e.theater)).forEach(t=>{ const o=document.createElement('option'); o.value=t; o.textContent=(THEATER_ZH[t]||t); fTheater.appendChild(o); });
function render(){
  const kw=q.value.trim().toLowerCase(), ft=fType.value, fth=fTheater.value;
  const rows=EVENTS.filter(e=>{
    if(ft && e.event_type!==ft) return false;
    if(fth && e.theater!==fth) return false;
    if(kw){ const hay=(e.title_zh+' '+e.title_en+' '+e.summary_zh+' '+e.summary_en+' '+(e.tags||'')).toLowerCase(); if(!hay.includes(kw)) return false; }
    return true;
  });
  tbody.innerHTML = rows.map(e=>{
    const disc=(e.disagreement_flag||'').toLowerCase().startsWith('y');
    const tags=(e.tags||'').split(';').filter(Boolean).map(t=>'<span class="tag">'+t+'</span>').join('');
    return '<tr><td>'+(e.date||'')+'</td><td>'+(THEATER_ZH[e.theater]||e.theater||'')+'</td><td>'+(TYPE_ZH[e.event_type]||e.event_type||'')+'</td>'
      +'<td><b>'+(e.title_zh||'')+'</b> / '+(e.title_en||'')+'<br><span style="color:#666">'+(e.summary_zh||'')+'</span> '+tags+'</td>'
      +'<td>'+(e.reliability||'')+'</td><td>'+(e.confidence||'')+'</td>'
      +'<td>'+(disc?'<span class="disc">分歧</span>':(e.source_side||''))+'</td></tr>';
  }).join('') || '<tr><td colspan="7" style="color:#888">无匹配</td></tr>';
}
q.addEventListener('input', render);
fType.addEventListener('change', render);
fTheater.addEventListener('change', render);
render();
</script>
</body>
</html>
"""

BRIEFING_PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s ｜ 简报</title>
<style>%s</style>
</head>
<body>
<header><h1>%s</h1><div class="sub"><a href="../../index.html">← 返回首页</a> ｜ <a href="../../briefings.html">全部简报</a> ｜ <a href="../../map.html">🗺 态势地图</a></div></header>
<div class="wrap lb">%s</div>
<footer><div class="wrap" style="padding:14px 20px">非官方、开源、中立汇编，仅供参考。<a href="../../index.html">返回首页</a></div></footer>
</body>
</html>
"""

ARCHIVE_PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>全部简报归档</title>
<style>%s</style>
</head>
<body>
<header><h1>全部简报归档</h1><div class="sub"><a href="index.html">← 返回首页</a> ｜ <a href="map.html">🗺 态势地图</a> ｜ 共 %d 份</div></header>
<div class="wrap archive">%s</div>
</body>
</html>
"""

GROUP_LABELS = {
    "daily": "每日快讯", "weekly": "每周复盘",
    "monthly": "每月深度", "yearly": "每年评估",
}


def scan_briefings() -> list[dict]:
    """扫描 briefings/*/ 下的 md，返回按组排序的结构化列表。"""
    items: list[dict] = []
    for sub in ("daily", "weekly", "monthly", "yearly"):
        d = BRIEF / sub
        if not d.exists():
            continue
        for md in sorted(d.glob("*.md"), reverse=True):
            text = md.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip() if text.splitlines() else md.stem
            items.append({"group": sub, "stem": md.stem, "title": title, "md": text})
    return items


def render_briefing_pages(items: list[dict]) -> None:
    """为每份简报生成独立渲染页 docs/briefings/<组>/<名>.html。"""
    for it in items:
        body = md_to_html(it["md"])
        html = BRIEFING_PAGE % (it["title"], CSS, it["title"], body)
        out = DOCS / "briefings" / it["group"] / (it["stem"] + ".html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    log(f"briefing pages rendered: {len(items)}")


def build_archive_html(items: list[dict]) -> str:
    """归档页主体：按组列出全部简报链接。"""
    parts: list[str] = []
    for group in ("daily", "weekly", "monthly", "yearly"):
        group_items = [i for i in items if i["group"] == group]
        if not group_items:
            continue
        parts.append(f"<section><h2>{GROUP_LABELS[group]} / {group}</h2><ul>")
        for it in group_items:
            parts.append(
                f'<li><a href="briefings/{it["group"]}/{it["stem"]}.html">{it["title"]}</a>'
                f'<span class="d">{it["stem"]}</span></li>'
            )
        parts.append("</ul></section>")
    return "\n".join(parts)


def build_latest_block(items: list[dict]) -> tuple[str, str]:
    """首页"今日最新情报"区块：取最新一份每日简报（无则回退其他组最新）。"""
    dailies = [i for i in items if i["group"] == "daily"]
    pool = dailies or items
    if not pool:
        return "", ""
    latest = pool[0]  # 已按文件名倒序
    body = md_to_html(latest["md"])
    block = (
        '<section class="latest">'
        f'<div class="lh"><h2>📌 今日最新情报</h2><span class="lmeta">{latest["stem"]}</span>'
        f'<a class="lbtn" href="briefings/{latest["group"]}/{latest["stem"]}.html">打开完整简报 ↗</a>'
        f'<a class="lbtn" href="briefings.html">全部简报归档</a>'
        f'<a class="lbtn" href="map.html">🗺 态势地图</a></div>'
        f'<div class="lb">{body}</div></section>'
    )
    rel = f'briefings/{latest["group"]}/{latest["stem"]}.html'
    return block, rel


def main() -> None:
    rows = read_events()
    cfg = load_config()
    title_zh = cfg["project"]["title_zh"]
    updated = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M +08:00")

    counter_type = Counter(r.get("event_type", "") for r in rows)
    counter_theater = Counter(r.get("theater", "") for r in rows)
    disagreements = sum(1 for r in rows if str(r.get("disagreement_flag", "")).lower().startswith("y"))

    stats = (
        f'<div class="card"><div class="num">{len(rows)}</div><div class="lbl">事件总数</div></div>'
        f'<div class="card"><div class="num">{disagreements}</div><div class="lbl">分歧事件</div></div>'
        f'<div class="card"><div class="num">{len(counter_type)}</div><div class="lbl">维度覆盖</div></div>'
        f'<div class="card"><div class="num">{len(counter_theater)}</div><div class="lbl">战区覆盖</div></div>'
    )

    type_zh = {k: v[0] for k, v in TYPE_LABELS.items()}
    rows_sorted = sorted(rows, key=lambda r: r.get("date", ""), reverse=True)

    items = scan_briefings()
    latest_block, latest_rel = build_latest_block(items)
    render_briefing_pages(items)

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(
        INDEX_HEAD % (title_zh, CSS, title_zh, updated, latest_block, stats, latest_rel,
                      json.dumps(rows_sorted, ensure_ascii=False),
                      json.dumps(type_zh, ensure_ascii=False),
                      json.dumps(THEATER_ZH, ensure_ascii=False)),
        encoding="utf-8")
    (DOCS / "events.json").write_text(json.dumps(rows_sorted, ensure_ascii=False), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    (DOCS / "briefings.html").write_text(
        ARCHIVE_PAGE % (CSS, len(items), build_archive_html(items)), encoding="utf-8")
    render_map_html(rows)
    log(f"pages rendered: {len(rows)} events, {len(items)} briefings -> docs/")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 战场态势地图（docs/map.html + map-data.json / roads-data.json / villages-data.json）
# 底图：腾讯地图 GL JS（合规图商；海外区域为"非默认场景"，key 用占位符，用户自行申请）
# 数据分层：首屏(战线/城市/重镇/热区) + zoom>=7 加载道路铁路 + zoom>=9 加载村庄(视野过滤)
# ---------------------------------------------------------------------------

MAP_STATIC = ROOT / "data" / "map" / "static"
MAP_SNAPSHOTS = ROOT / "data" / "map" / "snapshots"

# 战区 -> 中心坐标（用于事件热区标注；无地理语义的战区不参与）
THEATER_CENTER = {
    "east-avdiivka": (48.14, 37.74), "east-bakhmut": (48.60, 38.00),
    "east-donetsk": (48.35, 37.90), "east-luhansk": (48.90, 38.40),
    "south-kherson": (46.64, 33.30), "south-zaporizhzhia": (47.30, 35.60),
    "south-crimea": (45.30, 34.10), "north-kharkiv": (49.80, 36.90),
    "border-kursk": (51.20, 35.30), "black-sea": (45.00, 32.00),
    "homeland-ru": (51.50, 37.00), "homeland-ua": (49.50, 33.50),
}

# 海外地图渲染属于"非默认场景"：不内置任何 key，只放申请占位符。
# 真实 key 通过 CI 环境变量 TENCENT_MAP_KEY（GitHub Secrets）注入，仓库代码不含明文 key。
TENCENT_MAP_KEY_PLACEHOLDER = (
    "Please apply for your own key at the Tencent Location Service "
    "Open Platform (lbs.qq.com) and replace this placeholder")


def _map_key() -> str:
    return os.environ.get("TENCENT_MAP_KEY", "") or TENCENT_MAP_KEY_PLACEHOLDER


def _thin(points: list, step: int = 3) -> list:
    """抽稀：每隔 step 取一点，并保留末点（保证闭合/端点完整）。"""
    if len(points) <= 4:
        return points
    return points[::step] + ([points[-1]] if points[-1] != points[::step][-1] else [])


def _load_static_json(name: str) -> list:
    p = MAP_STATIC / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log(f"map static {name} parse failed; use empty")
    return []


def _geojson_polygons(path, thin_step: int = 3) -> list[list[list]]:
    """读 DeepState 快照 geojson -> [ [ [lat,lon],... ], ... ]（每 polygon 取外环并抽稀）。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in d.get("features", []):
        g = f.get("geometry", {})
        if g.get("type") == "MultiPolygon":
            for poly in g.get("coordinates", []):
                if poly:
                    ring = _thin([[c[1], c[0]] for c in poly[0]], thin_step)
                    if len(ring) > 2:
                        out.append(ring)
        elif g.get("type") == "Polygon":
            ring = _thin([[c[1], c[0]] for c in g.get("coordinates", [])[0]], thin_step)
            if len(ring) > 2:
                out.append(ring)
    return out


# 西里尔/拉丁字母（俄语/乌克兰语/英语名需要词边界匹配，避免普通词误判为地名）
_LETTERS = r"a-zA-Zа-яА-ЯіїєґІЇЄҐ"

# 常见普通词黑名单：即便命中村庄名也不打点（"第一/新/旧/中心/五月"等）
_COMMON_WORDS = {
    "первый", "второй", "третий", "новый", "новая", "новое", "старый", "старая",
    "центр", "центральный", "завод", "село", "город", "деревня", "дом", "дома",
    "май", "июнь", "июль", "август", "день", "год", "улица", "район",
    "перша", "нова", "стара", "селище", "місто", "вулиця",
}


def _build_name_index() -> dict[str, tuple[float, float, bool]]:
    """城市/镇/村庄/重镇/枢纽 -> (lat, lon, 是否小地名)。

    is_minor=True（村庄）要求名字 >=5 字符且词边界匹配，减少"Рекорд"类普通词误判。
    """
    idx: dict[str, tuple[float, float, bool]] = {}
    for c in _load_static_json("cities.json"):
        if c.get("n"):
            idx[c["n"]] = (c["lat"], c["lon"], False)
    for v in _load_static_json("villages.json"):
        if v.get("n") and len(v["n"]) >= 5:  # 短名易误匹配，跳过
            idx[v["n"]] = (v["lat"], v["lon"], True)
    for s in _load_static_json("strongholds.json"):
        if s.get("n"):
            idx[s["n"]] = (s["lat"], s["lon"], False)
        if s.get("en"):
            idx[s["en"]] = (s["lat"], s["lon"], False)
    return idx


def _name_hits(text: str, name: str) -> bool:
    """地名匹配：中文名直接子串；西里尔/拉丁名要求词边界（两侧不是字母）。

    text 已转小写，故西里尔/拉丁名也要先 lower 再匹配。
    """
    if re.search(r"[" + _LETTERS + "]", name):
        n = name.lower()
        pat = r"(?<![" + _LETTERS + "])" + re.escape(n) + r"(?![" + _LETTERS + "])"
        return re.search(pat, text) is not None
    return name in text


def build_map_data(rows: list[dict]) -> dict:
    """汇总首屏地图数据（战线/城市/重镇/热区/事件精确点），不含道路铁路村庄（按需加载）。"""
    # 快照优先取 data/map/snapshots/；若无（如 CI 未归档），回退到 data/raw/ 里的 DeepState 文件
    snaps = sorted(MAP_SNAPSHOTS.glob("*.geojson"), reverse=True) if MAP_SNAPSHOTS.exists() else []
    if not snaps and RAW.exists():
        snaps = sorted(RAW.glob("DeepStateMap_*.geojson"), reverse=True)[:2]
    control, control_prev = None, None
    if snaps:
        control = {"date": snaps[0].stem, "polygons": _geojson_polygons(snaps[0])}
    if len(snaps) > 1:
        control_prev = {"date": snaps[1].stem, "polygons": _geojson_polygons(snaps[1])}

    # 事件红点只统计"当日"：最近 48 小时（北京时间，与每日简报 [昨天,今天] 覆盖一致），
    # 避免把全部历史事件都打上图（满图红点）
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    recent = [r for r in rows if (r.get("date") or "") >= yesterday]
    recent_ids = {r.get("event_id") for r in recent}

    # 战区级热区（背景粒度，仅当日事件）
    hot = Counter()
    for r in recent:
        t = r.get("theater", "")
        if t in THEATER_CENTER:
            hot[t] += 1
    event_areas = [{"key": k, "zh": THEATER_ZH.get(k, k),
                    "lat": THEATER_CENTER[k][0], "lon": THEATER_CENTER[k][1],
                    "count": v} for k, v in hot.items()]

    # 精确地名匹配：当日事件标题里出现的地名 -> 坐标打点（同点聚合）。
    # 只匹配标题（摘要太长、含大量普通词，会拖慢匹配且易误判）
    idx = _build_name_index()
    pts: dict[tuple, dict] = {}
    for r in recent:
        text = (" " + r.get("title_zh", "") + " " + r.get("title_en", "") + " ").lower()
        for name, (lat, lon, minor) in idx.items():
            if len(name) <= 2 or name.lower() in _COMMON_WORDS:
                continue
            if minor and len(name) < 5:
                continue  # 村庄短名直接跳过
            if _name_hits(text, name):
                key = (round(lat, 3), round(lon, 3))
                e = pts.setdefault(key, {"lat": round(lat, 3), "lon": round(lon, 3),
                                         "names": set(), "count": 0})
                e["names"].add(name)
                e["count"] += 1
    event_points = [{"lat": e["lat"], "lon": e["lon"],
                     "names": sorted(e["names"])[:4], "count": e["count"]}
                    for e in pts.values()]

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M +08:00"),
        "control": control,
        "control_prev": control_prev,
        "cities": _load_static_json("cities.json"),
        "strongholds": _load_static_json("strongholds.json"),
        "event_areas": event_areas,
        "event_points": event_points,
        "event_range": f"{yesterday} ~ {today}",
        "events_total": len(recent),
        "events_archive_total": len(rows),
    }


MAP_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>战场态势地图</title>
<style>
  html,body{margin:0;padding:0;height:100%;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a}
  #map{width:100%;height:100vh}
  .panel{position:absolute;background:#fff;border:1px solid #e3e3e3;border-radius:12px;
    padding:10px 14px;font-size:12px;line-height:1.8;box-shadow:0 2px 8px rgba(0,0,0,.08)}
  #legend{left:14px;top:14px;z-index:999}
  #meta{right:14px;top:14px;z-index:999;text-align:right;color:#555}
  .lg{display:flex;align-items:center;gap:8px;white-space:nowrap;cursor:pointer;border-radius:6px;padding:2px 6px;margin:0 -6px}
  .lg:hover{background:#f2f6fb}
  .lg.off{opacity:.35}
  .sw{display:inline-block;width:16px;height:10px;border-radius:3px;flex:none}
  .swl{display:inline-block;width:16px;height:2px;flex:none}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex:none}
  #legend h3{margin:0 0 6px;font-size:13px;font-weight:500}
  #legend .hint{color:#888;font-size:11px;margin:-2px 0 6px}
  #legend a{color:#185fa5;text-decoration:none}
  #loading{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:1000;
    background:#fff;border:1px solid #e3e3e3;border-radius:10px;padding:10px 18px;font-size:13px;display:none}
</style>
</head>
<body>
<div id="map"></div>
<div id="loading">正在加载图层…</div>
<div id="legend" class="panel">
  <h3>图例</h3>
  <div class="hint">点击项目可开关图层</div>
  <div class="lg on" data-layer="control"><span class="sw" style="background:#e24b4a;opacity:.45"></span>俄控区（当日）</div>
  <div class="lg on" data-layer="prev"><span class="swl" style="border-top:2px dashed #7f77dd"></span>前一日控制线</div>
  <div class="lg on" data-layer="roads"><span class="swl" style="background:#888"></span>主要道路</div>
  <div class="lg on" data-layer="rail"><span class="swl" style="background:#333;border-top:2px solid #333"></span>铁路</div>
  <div class="lg on" data-layer="cities"><span class="dot" style="background:#185fa5"></span>城市</div>
  <div class="lg on" data-layer="strongholds"><span class="dot" style="background:#a32d2d;width:11px;height:11px;clip-path:polygon(50% 0,100% 38%,82% 100%,18% 100%,0 38%)"></span>防御重镇</div>
  <div class="lg on" data-layer="hubs"><span class="dot" style="background:#d85a30;width:10px;height:10px;transform:rotate(45deg)"></span>交通枢纽</div>
  <div class="lg on" data-layer="events"><span class="dot" style="background:#e24b4a;border:2px solid #fff"></span>当日事件</div>
  <div class="lg" data-layer="villages"><span class="dot" style="background:#b4b2a9"></span>村庄（缩放 9 级+）</div>
  <div style="margin-top:8px"><a href="index.html">← 返回首页</a> ｜ <a href="briefings.html">简报</a></div>
</div>
<div id="meta" class="panel">
  数据：DeepState 每日快照 + OSM(ODbL) + 情报标注<br>
  快照：__SNAP_INFO__<br>
  事件红点：__EVENT_RANGE__（共 __EVENT_NUM__ 条）<br>
  生成：__GEN_AT__
</div>
<script type="text/javascript">
const MAP_DATA = __MAP_DATA__;
</script>
<script src="https://map.qq.com/api/gljs?v=1.exp&key=__MAP_KEY__"></script>
<script>
if ("__MAP_KEY__".indexOf("replace this placeholder") !== -1) {
  document.getElementById('map').innerHTML =
    '<div style="padding:40px;font-family:sans-serif;color:#a32d2d">' +
    '底图 key 未配置：请在腾讯位置服务开放平台(lbs.qq.com)申请 key 后，' +
    '替换 docs/map.html 中 script 标签的 key 参数。</div>';
}
const ctl = MAP_DATA.control, prev = MAP_DATA.control_prev;
const map = new TMap.Map('map', { center: new TMap.LatLng(48.6, 36.5), zoom: 6 });
const info = new TMap.InfoWindow({ map, position: new TMap.LatLng(48.6, 36.5), offset: { x: 0, y: -32 } });
const showInfo = (extra, pos) => { info.setPosition(pos); info.setContent('<div style="font-size:13px;max-width:260px;line-height:1.6">'+extra+'</div>'); info.open(); };
const LL = (p) => new TMap.LatLng(p[0], p[1]);

/* 图层注册表 + 显隐状态（undefined=默认开） */
const L = {};
const STATE = {};

/* 前一日对比线 */
if (prev && prev.polygons.length) {
  L.prev = new TMap.MultiPolygon({ map, styles: { p: new TMap.PolygonStyle({ color: '#7f77dd', showBorder: true, borderColor: '#7f77dd', borderWidth: 2, showBorderDash: true, borderDash: [6,4] }) },
    geometries: prev.polygons.map((ring, i) => ({ id: 'pp'+i, styleId: 'p', paths: [ring.map(LL)] })) });
}
/* 当日俄控区 */
if (ctl && ctl.polygons.length) {
  L.control = new TMap.MultiPolygon({ map, styles: { p: new TMap.PolygonStyle({ color: 'rgba(226,75,74,0.35)', showBorder: true, borderColor: '#a32d2d', borderWidth: 2 }) },
    geometries: ctl.polygons.map((ring, i) => ({ id: 'c'+i, styleId: 'p', paths: [ring.map(LL)] })) });
}
/* 城市分级：大城市(所有缩放) + 小城镇(zoom>=8)，避免低缩放满屏点 */
if (MAP_DATA.cities && MAP_DATA.cities.length) {
  const big = new TMap.MarkerStyle({ width: 8, height: 8, anchor: { x: 4, y: 4 }, color: '#185fa5' });
  const small = new TMap.MarkerStyle({ width: 5, height: 5, anchor: { x: 2.5, y: 2.5 }, color: '#85b7eb' });
  const mk = (c, i) => ({ id: 'ci'+i, styleId: c.p === 'city' ? 'big' : 'small',
    position: new TMap.LatLng(c.lat, c.lon), extra: '<b>'+c.n+'</b>' });
  const cityList = MAP_DATA.cities.filter(c => c.p === 'city');
  const townList = MAP_DATA.cities.filter(c => c.p !== 'city');
  if (cityList.length) {
    L.cities = new TMap.MultiMarker({ map, styles: { big, small },
      geometries: cityList.map((c, i) => mk(c, i)) });
    L.cities.on('click', (e) => showInfo(e.geometry.extra, e.geometry.position));
  }
  if (townList.length) {
    L.towns = new TMap.MultiMarker({ map, styles: { big, small },
      geometries: townList.map((c, i) => mk(c, i)) });
    L.towns.on('click', (e) => showInfo(e.geometry.extra, e.geometry.position));
    L.towns.setVisible(false);
  }
}
/* 重镇 / 枢纽（拆两个图层，便于图例分别开关） */
if (MAP_DATA.strongholds && MAP_DATA.strongholds.length) {
  const sh = new TMap.MarkerStyle({ width: 13, height: 13, anchor: { x: 6.5, y: 6.5 }, color: '#a32d2d' });
  const hu = new TMap.MarkerStyle({ width: 11, height: 11, anchor: { x: 5.5, y: 5.5 }, color: '#d85a30' });
  const mk = (s, i) => ({ id: 's'+i, styleId: s.type === 'stronghold' ? 'sh' : 'hu',
    position: new TMap.LatLng(s.lat, s.lon),
    extra: '<b>'+s.n+'</b> <span style="color:#777">'+s.en+'</span><br>'+s.note });
  const shs = MAP_DATA.strongholds.filter(s => s.type === 'stronghold').map((s, i) => mk(s, i));
  const hubs = MAP_DATA.strongholds.filter(s => s.type !== 'stronghold').map((s, i) => mk(s, i));
  L.strongholds = new TMap.MultiMarker({ map, styles: { sh, hu }, geometries: shs });
  L.strongholds.on('click', (e) => showInfo(e.geometry.extra, e.geometry.position));
  L.hubs = new TMap.MultiMarker({ map, styles: { sh, hu }, geometries: hubs });
  L.hubs.on('click', (e) => showInfo(e.geometry.extra, e.geometry.position));
}
/* 当日事件：战区热区 + 精确地点合并为一层 */
{
  const geoms = [];
  const styles = {};
  if (MAP_DATA.event_areas && MAP_DATA.event_areas.length) {
    MAP_DATA.event_areas.forEach((a, i) => {
      const size = Math.min(12 + a.count, 26);
      styles['a'+i] = new TMap.MarkerStyle({ width: size, height: size, anchor: { x: size/2, y: size/2 }, color: '#e24b4a', borderWidth: 2, borderColor: '#fff' });
      geoms.push({ id: 'a'+i, styleId: 'a'+i, position: new TMap.LatLng(a.lat, a.lon),
        extra: '<b>'+a.zh+'</b>：当日 '+a.count+' 条事件' });
    });
  }
  if (MAP_DATA.event_points && MAP_DATA.event_points.length) {
    MAP_DATA.event_points.forEach((p, i) => {
      styles['p'+i] = new TMap.MarkerStyle({ width: 12, height: 12, anchor: { x: 6, y: 6 }, color: '#ff5722', borderWidth: 2, borderColor: '#fff' });
      geoms.push({ id: 'p'+i, styleId: 'p'+i, position: new TMap.LatLng(p.lat, p.lon),
        extra: '<b>事件地点：'+p.names.join(' / ')+'</b><br>关联 '+p.count+' 条事件' });
    });
  }
  if (geoms.length) {
    L.events = new TMap.MultiMarker({ map, styles, geometries: geoms });
    L.events.on('click', (e) => showInfo(e.geometry.extra, e.geometry.position));
  }
}
/* 道路 + 铁路（zoom>=7 按需加载一次） */
let roadsLoaded = false;
function loadRoads() {
  if (roadsLoaded) return;
  roadsLoaded = true;
  const ld = document.getElementById('loading'); ld.style.display = 'block';
  fetch('roads-data.json').then(r => r.json()).then(d => {
    ld.style.display = 'none';
    L.roads = new TMap.MultiPolyline({ map, styles: { r: new TMap.PolylineStyle({ color: '#999', lineWidth: 2 }) },
      geometries: d.roads.map((w, i) => ({ id: 'r'+i, styleId: 'r', paths: w.c.map(LL) })) });
    L.rail = new TMap.MultiPolyline({ map, styles: { r: new TMap.PolylineStyle({ color: '#333', lineWidth: 1.5 }) },
      geometries: d.rail.map((w, i) => ({ id: 'l'+i, styleId: 'r', paths: w.c.map(LL) })) });
    applyState();
  }).catch(() => { ld.style.display = 'none'; });
}
/* 村庄（zoom>=9 按需加载 + 视野过滤渲染） */
let villagesData = null, villagesLoaded = false;
function updateVillages() {
  if (map.getZoom() < 9) { if (L.villages) L.villages.setVisible(false); return; }
  if (!villagesLoaded) {
    villagesLoaded = true;
    fetch('villages-data.json').then(r => r.json()).then(d => {
      villagesData = d.villages;
      const vs = new TMap.MarkerStyle({ width: 3, height: 3, anchor: { x: 1.5, y: 1.5 }, color: '#b4b2a9' });
      L.villages = new TMap.MultiMarker({ map, styles: { vs }, geometries: [] });
      L.villages.on('click', (e) => showInfo('<b>'+e.geometry.name+'</b>', e.geometry.position));
      renderVillages();
    });
    return;
  }
  renderVillages();
}
function renderVillages() {
  if (!L.villages || !villagesData) return;
  const b = map.getBounds();
  const vis = [];
  for (const v of villagesData) {
    const ll = new TMap.LatLng(v.lat, v.lon);
    if (b.contains(ll)) vis.push({ id: 'v'+vis.length, styleId: 'vs', position: ll, name: v.n, extra: v.n });
  }
  L.villages.setGeometries(vis);
  L.villages.setVisible(map.getZoom() >= 9 && STATE.villages !== false);
}
/* 图例点击：开关图层 */
function toggleLayer(name) {
  const el = document.querySelector('#legend .lg[data-layer="'+name+'"]');
  if (!el) return;
  const willBeOn = el.classList.contains('off');
  el.classList.toggle('off', !willBeOn);
  STATE[name] = willBeOn;
  if (name === 'roads' && willBeOn && !roadsLoaded) { loadRoads(); return; }
  applyState();
}
function applyState() {
  if (L.control) L.control.setVisible(STATE.control !== false);
  if (L.prev) L.prev.setVisible(STATE.prev !== false);
  if (L.roads) L.roads.setVisible(STATE.roads !== false);
  if (L.rail) L.rail.setVisible(STATE.rail !== false);
  if (L.cities) L.cities.setVisible(STATE.cities !== false);
  if (L.towns) L.towns.setVisible(map.getZoom() >= 8 && STATE.cities !== false);
  if (L.strongholds) L.strongholds.setVisible(STATE.strongholds !== false);
  if (L.hubs) L.hubs.setVisible(STATE.hubs !== false);
  if (L.events) L.events.setVisible(STATE.events !== false);
  if (L.villages) L.villages.setVisible(map.getZoom() >= 9 && STATE.villages !== false);
}
document.querySelectorAll('#legend .lg[data-layer]').forEach(el => {
  el.addEventListener('click', () => toggleLayer(el.dataset.layer));
});
/* 缩放联动：城市分级 + 道路 + 村庄 */
let zoomTimer = null;
function onZoom() {
  if (L.towns) L.towns.setVisible(map.getZoom() >= 8 && STATE.cities !== false);
  if (map.getZoom() >= 7) loadRoads();
  updateVillages();
}
map.on('zoom_changed', () => { clearTimeout(zoomTimer); zoomTimer = setTimeout(onZoom, 200); });
map.on('center_changed', () => { clearTimeout(zoomTimer); zoomTimer = setTimeout(updateVillages, 200); });
</script>
</body>
</html>
"""


def render_map_html(rows: list[dict]) -> None:
    md = build_map_data(rows)
    (DOCS / "map-data.json").write_text(json.dumps(md, ensure_ascii=False), encoding="utf-8")

    # 独立按需加载文件：道路/铁路合并抽稀；村庄抽稀
    def _thin_lines(items: list, step: int, precision: int = 3) -> list:
        return [{"n": w.get("n", ""), "c": [[round(p[0], precision), round(p[1], precision)]
                                            for p in _thin(w["c"], step)]}
                for w in items if len(w.get("c", [])) >= 2]

    roads = _load_static_json("roads.json")
    rail = _load_static_json("rail.json")
    villages = _load_static_json("villages.json")
    (DOCS / "roads-data.json").write_text(
        json.dumps({"roads": _thin_lines(roads, 3), "rail": _thin_lines(rail, 2)},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # 村庄是点数据（lat/lon），降精度到 3 位（约 110m）
    vd = [{"n": v.get("n", ""), "lat": round(v["lat"], 3), "lon": round(v["lon"], 3)}
          for v in villages]
    (DOCS / "villages-data.json").write_text(
        json.dumps({"villages": vd}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    snap_info = "无快照"
    if md["control"]:
        snap_info = md["control"]["date"]
        if md["control_prev"]:
            snap_info += "（对比 " + md["control_prev"]["date"] + "）"
    html = (MAP_HTML
            .replace("__MAP_DATA__", json.dumps(md, ensure_ascii=False))
            .replace("__MAP_KEY__", _map_key())
            .replace("__SNAP_INFO__", snap_info)
            .replace("__EVENT_RANGE__", md["event_range"])
            .replace("__EVENT_NUM__", str(md["events_total"]))
            .replace("__GEN_AT__", md["generated_at"]))
    (DOCS / "map.html").write_text(html, encoding="utf-8")
    log(f"map rendered: control={'yes' if md['control'] else 'no'} "
        f"cities={len(md['cities'])} strongholds={len(md['strongholds'])} "
        f"event_areas={len(md['event_areas'])} event_points={len(md['event_points'])} -> docs/")


if __name__ == "__main__":
    main()

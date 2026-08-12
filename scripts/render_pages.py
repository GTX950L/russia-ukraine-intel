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
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from utils import DOCS, MASTER, THEATER_ZH, TYPE_LABELS, read_events, load_config, log, BRIEF

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
<header><h1>%s</h1><div class="sub"><a href="../../index.html">← 返回首页</a> ｜ <a href="../../briefings.html">全部简报</a></div></header>
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
<header><h1>全部简报归档</h1><div class="sub"><a href="index.html">← 返回首页</a> ｜ 共 %d 份</div></header>
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
        f'<a class="lbtn" href="briefings.html">全部简报归档</a></div>'
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
    log(f"pages rendered: {len(rows)} events, {len(items)} briefings -> docs/")


if __name__ == "__main__":
    main()

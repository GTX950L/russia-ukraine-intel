"""⑤ 渲染层：读 events.csv → 生成 docs/ 站点（仪表盘 + 简报渲染页 + 归档页）。

采用 GitHub Pages "Deploy from branch: main / docs" 模式（仓库根 .nojekyll 关闭 Jekyll）。
站点为纯静态：前端用内嵌 EVENTS 做客户端筛选，无需后端。
额外生成：
- docs/briefings.html         全部简报归档页
- docs/briefings/<组>/<名>.html  每份简报的独立渲染页（md → html）
- 首页顶部"今日要点"区块（自动从最新每日简报提取精简要点卡片，不再内嵌全文）

视觉设计：地图为核心，首页 = 统计卡 + 态势地图(iframe) + 今日要点卡片 + 事件检索表；
全站统一 CSS 变量设计体系（浅色主题）。
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
# 页面模板（浅色主题 · 地图为核心的简洁视觉体系）
# ---------------------------------------------------------------------------

CSS = """\
  :root {
    --bg:#f5f6f8; --fg:#1c2330; --mut:#667085; --bd:#e4e8ef;
    --card:#ffffff; --acc:#1a5fb4; --acc-soft:#eaf1fb;
    --red:#c0392b; --red-soft:#fdecea;
    --amber:#b36b00; --amber-soft:#fdf3e2;
    --green:#1e7d4f; --green-soft:#e8f5ee;
    --purple:#7f77dd; --shadow:0 1px 3px rgba(23,33,60,.06),0 4px 14px rgba(23,33,60,.05);
  }
  * { box-sizing:border-box; }
  body { font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif; margin:0; color:var(--fg); background:var(--bg); }
  a { color:var(--acc); text-decoration:none; }
  a:hover { text-decoration:underline; }
  /* ---------- 顶栏 ---------- */
  .topbar { background:var(--card); border-bottom:1px solid var(--bd); }
  .topbar-in { max-width:1200px; margin:0 auto; padding:18px 22px 12px; display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
  .topbar h1 { margin:0; font-size:20px; letter-spacing:.2px; }
  .topbar h1 .dot { color:var(--red); }
  .sub { color:var(--mut); font-size:12.5px; }
  nav { margin:10px 0 0; display:flex; gap:6px; flex-wrap:wrap; }
  nav a { font-size:12.5px; padding:4px 12px; border-radius:999px; border:1px solid var(--bd); color:var(--fg); background:#fafbfc; }
  nav a:hover { background:var(--acc-soft); border-color:#c9d8ef; text-decoration:none; }
  .wrap { max-width:1200px; margin:0 auto; padding:20px 22px 70px; }
  /* ---------- 统计卡 ---------- */
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:0 0 18px; }
  .card { background:var(--card); border:1px solid var(--bd); border-radius:14px; padding:14px 16px; box-shadow:var(--shadow); }
  .card .num { font-size:24px; font-weight:700; color:var(--fg); line-height:1.2; }
  .card .num small { font-size:13px; color:var(--mut); font-weight:500; }
  .card .lbl { font-size:12px; color:var(--mut); margin-top:3px; display:flex; align-items:center; gap:6px; }
  .card .ico { font-size:15px; }
  .card.acc .num { color:var(--acc); } .card.red .num { color:var(--red); }
  .card.green .num { color:var(--green); } .card.amber .num { color:var(--amber); }
  /* ---------- 通用区块卡 ---------- */
  .sec { background:var(--card); border:1px solid var(--bd); border-radius:14px; box-shadow:var(--shadow); margin:0 0 18px; overflow:hidden; }
  .sec-h { display:flex; align-items:center; gap:10px; padding:13px 18px; border-bottom:1px solid var(--bd); flex-wrap:wrap; }
  .sec-h h2 { margin:0; font-size:15.5px; }
  .sec-h .muted { color:var(--mut); font-size:12px; }
  .sec-h .sp { flex:1; }
  .btn { font-size:12px; border:1px solid var(--bd); border-radius:8px; padding:5px 12px; color:var(--acc); background:#fafbfc; text-decoration:none; }
  .btn:hover { background:var(--acc-soft); text-decoration:none; }
  .btn.red { color:var(--red); border-color:#f0c8c2; } .btn.red:hover { background:var(--red-soft); }
  .sec-b { padding:14px 18px; }
  /* ---------- 态势地图 ---------- */
  .map-frame { display:block; width:100%; height:520px; border:0; background:#eef1f5; }
  @media (max-width:720px){ .map-frame { height:60vh; min-height:340px; } }
  /* ---------- 今日要点 ---------- */
  .pts { display:flex; flex-direction:column; }
  .grp-t { font-size:12px; color:var(--acc); font-weight:600; margin:12px 0 6px; display:flex; align-items:center; gap:8px; }
  .grp-t:first-child { margin-top:0; }
  .grp-t::after { content:""; flex:1; height:1px; background:var(--bd); }
  .pt { border:1px solid var(--bd); border-left:3px solid var(--acc); border-radius:10px; padding:9px 13px; margin:0 0 8px; cursor:pointer; transition:background .12s; }
  .pt:hover { background:#fafbfd; }
  .pt .row1 { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .pt .zh { font-weight:600; font-size:13.5px; }
  .pt .en { color:var(--mut); font-size:12px; margin-top:2px; }
  .pt .sum { color:#4a5568; font-size:12.5px; margin-top:5px; padding-top:6px; border-top:1px dashed var(--bd); line-height:1.6; }
  .rel { display:inline-block; min-width:20px; text-align:center; font-size:10.5px; font-weight:700; border-radius:5px; padding:1px 5px; color:#fff; }
  .rel-A { background:var(--green); } .rel-B { background:var(--acc); } .rel-C { background:#e08c2e; }
  .rel-D { background:var(--red); } .rel-E { background:#7a1f14; } .rel-F { background:#4a4a4a; }
  .rel-x { background:#9aa3b2; }
  .conf { font-size:11px; color:var(--mut); border:1px solid var(--bd); border-radius:5px; padding:1px 6px; }
  .flag { font-size:11px; color:var(--red); background:var(--red-soft); border-radius:5px; padding:1px 6px; font-weight:600; }
  .src { font-size:11px; color:var(--mut); }
  /* ---------- 信源对照 ---------- */
  details.cross { border:1px solid var(--bd); border-radius:10px; margin:10px 0; }
  details.cross summary { cursor:pointer; padding:10px 14px; font-size:13px; font-weight:600; color:var(--fg); list-style:none; display:flex; align-items:center; gap:8px; }
  details.cross summary::before { content:"▸"; color:var(--acc); transition:transform .15s; }
  details.cross[open] summary::before { transform:rotate(90deg); }
  details.cross .box { padding:0 14px 12px; }
  details.cross table { width:100%; border-collapse:collapse; font-size:12px; margin:4px 0; }
  details.cross th, details.cross td { text-align:left; padding:7px 9px; border-bottom:1px solid var(--bd); vertical-align:top; }
  details.cross th { background:#fafbfc; }
  /* ---------- 事件检索 ---------- */
  .filters { display:flex; gap:10px; flex-wrap:wrap; }
  input,select { padding:8px 11px; border:1px solid var(--bd); border-radius:9px; font-size:13px; background:#fff; color:var(--fg); }
  input { flex:1 1 260px; }
  table.ev { width:100%; border-collapse:collapse; font-size:12.5px; }
  table.ev th, table.ev td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--bd); vertical-align:top; }
  table.ev th { background:#fafbfc; position:sticky; top:0; font-weight:600; color:var(--mut); font-size:11.5px; white-space:nowrap; }
  table.ev tbody tr:hover { background:#f7f9fd; }
  table.ev td.et .en { display:block; color:var(--mut); font-size:11.5px; margin-top:1px; }
  table.ev td.et .sum { display:block; color:#4a5568; font-size:11.5px; margin-top:3px; }
  .tag { display:inline-block; background:var(--acc-soft); color:var(--acc); border-radius:6px; padding:1px 7px; font-size:10.5px; margin:2px 4px 0 0; }
  .disc { color:var(--red); font-weight:700; font-size:11.5px; }
  .empty { color:#98a2b3; text-align:center; padding:26px 0 !important; }
  .morebar { text-align:center; padding:12px 0 4px; }
  .morebar button { border:1px solid var(--bd); background:#fff; border-radius:9px; padding:8px 22px; font-size:13px; color:var(--acc); cursor:pointer; }
  .morebar button:hover { background:var(--acc-soft); }
  .cnt { font-size:12px; color:var(--mut); }
  /* ---------- 简报页正文 ---------- */
  .lb { font-size:14px; line-height:1.75; }
  .lb h1 { font-size:20px; margin:6px 0 12px; }
  .lb h2 { font-size:16px; margin:22px 0 8px; padding-bottom:6px; border-bottom:2px solid var(--acc-soft); }
  .lb h3 { font-size:14.5px; margin:16px 0 6px; }
  .lb blockquote { margin:10px 0; padding:9px 14px; background:#fafbfc; border-left:3px solid var(--acc); color:var(--mut); font-size:13px; border-radius:0 8px 8px 0; }
  .lb ul { margin:8px 0; padding-left:24px; }
  .lb li { margin:4px 0; }
  .lb table { font-size:12.5px; margin:10px 0; }
  .lb hr { border:none; border-top:1px dashed var(--bd); margin:18px 0; }
  .lb code { background:#f1f3f7; border-radius:4px; padding:1px 5px; font-size:12.5px; }
  .lb a { word-break:break-all; }
  .lb p { margin:10px 0; }
  .lb th, .lb td { border-bottom:1px solid var(--bd); padding:6px 8px; text-align:left; }
  .lb th { background:#fafbfc; }
  /* ---------- 归档页 ---------- */
  .archive { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:14px; }
  .archive .ag { background:var(--card); border:1px solid var(--bd); border-radius:14px; box-shadow:var(--shadow); overflow:hidden; }
  .archive .ag-h { padding:12px 16px; font-size:14.5px; font-weight:700; border-bottom:1px solid var(--bd); background:linear-gradient(180deg,#fafbfc,#fff); }
  .archive ul { list-style:none; padding:0; margin:0; }
  .archive li { padding:9px 16px; border-bottom:1px dashed #eef1f6; font-size:13px; display:flex; align-items:center; gap:10px; }
  .archive li:last-child { border-bottom:none; }
  .archive li a { text-decoration:none; font-weight:500; }
  .archive .d { color:var(--mut); font-size:11.5px; margin-left:auto; white-space:nowrap; }
  footer { color:var(--mut); font-size:12px; border-top:1px solid var(--bd); margin-top:26px; padding-top:14px; line-height:1.8; }
"""


# ---------------------------------------------------------------------------
# 首页：今日要点解析（从最新每日简报 md 提取精简卡片，替代全文内嵌）
# ---------------------------------------------------------------------------

def parse_daily_points(md: str) -> list[dict]:
    """解析每日简报 md → 分组要点列表。

    目标行格式（由 templates/daily.md 固定生成）：
      ## 战线状况 / Frontline
      - **标题(中)** / Title(EN) ｜ 可靠B 置信3 来源方:third ⚠分歧
        - 中：中文摘要
        - EN：English summary
    解析失败（结构变化）时返回空列表，调用方回退到全文折叠块。
    """
    groups: list[dict] = []
    cur: dict | None = None
    for raw in md.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        m = re.match(r"^##\s+(.+?)\s*/\s*(.+)$", line)
        if m:
            cur = {"zh": m.group(1).strip(), "en": m.group(2).strip(), "items": []}
            groups.append(cur)
            continue
        m = re.match(r"^-\s+\*\*(.+?)\*\*\s*/\s*(.+)$", line)
        if m and cur is not None:
            zh = m.group(1).strip()
            rest = m.group(2).strip()
            item = {"zh": zh, "en": "", "rel": "", "conf": "", "src": "",
                    "disc": False, "sum_zh": "", "sum_en": ""}
            # rest 形如 "EN 标题 ｜ 可靠B 置信3 来源方:third ⚠分歧"
            meta = re.search(r"｜\s*(.*)$", rest)
            if meta:
                item["en"] = rest[: meta.start()].strip()
                mtxt = meta.group(1)
                rm = re.search(r"可靠\s*([A-Fa-f])", mtxt)
                if rm:
                    item["rel"] = rm.group(1).upper()
                cm = re.search(r"置信\s*(\d)", mtxt)
                if cm:
                    item["conf"] = cm.group(1)
                sm = re.search(r"来源方[:：]\s*(\S+)", mtxt)
                if sm:
                    item["src"] = sm.group(1).strip(",;。")
                item["disc"] = ("⚠" in mtxt or "分歧" in mtxt)
            else:
                item["en"] = rest
            cur["items"].append(item)
            continue
        m = re.match(r"^-\s*(中|EN|en)[:：]\s*(.+)$", line)
        if m and cur is not None and cur["items"]:
            if m.group(1) == "中":
                cur["items"][-1]["sum_zh"] = m.group(2).strip()
            else:
                cur["items"][-1]["sum_en"] = m.group(2).strip()
    return [g for g in groups if g["items"]]


def points_block(md: str, limit: int = 14) -> str:
    """今日要点卡片 HTML（每组至多 limit 条，超出折叠在"完整简报"里）。"""
    groups = parse_daily_points(md)
    if not groups:
        return ""
    parts = ['<div class="pts">']
    shown = 0
    for g in groups:
        if shown >= limit:
            break
        parts.append(f'<div class="grp-t">{g["zh"]} <span style="color:#98a2b3;font-weight:400">{g["en"]}</span></div>')
        for it in g["items"]:
            if shown >= limit:
                break
            shown += 1
            rel = it["rel"] or "x"
            disc = '<span class="flag">⚠ 分歧</span>' if it["disc"] else ""
            conf = f'<span class="conf">置信{it["conf"]}</span>' if it["conf"] else ""
            src = f'<span class="src">来源方:{it["src"]}</span>' if it["src"] else ""
            sum_html = ""
            if it["sum_zh"] or it["sum_en"]:
                s = f'<div class="sum" hidden>{it["sum_zh"] or ""}'
                if it["sum_en"] and it["sum_en"] != it["sum_zh"]:
                    s += f'<br><span style="color:#98a2b3">{it["sum_en"]}</span>'
                sum_html = s + "</div>"
            parts.append(
                f'<div class="pt" onclick="this.querySelector(\'.sum\')?.toggleAttribute(\'hidden\')">'
                f'<div class="row1"><span class="zh">{it["zh"]}</span>'
                f'<span class="rel rel-{rel}">{rel}</span>{conf}{disc}{src}</div>'
                f'<div class="en">{it["en"]}</div>{sum_html}</div>'
            )
    parts.append("</div>")
    return "\n".join(parts)


def crosscheck_block(md: str) -> str:
    """信源对照（最新简报"信源对照 / Source Cross-check"小节）→ 折叠块。"""
    m = re.search(r"##\s*信源对照.*?(?=\n##\s|\Z)", md, flags=re.S)
    if not m:
        return ""
    tbl = ""
    for row in m.group(0).split("\n"):
        if row.strip().startswith("|") and not re.match(r"^[\s:\-|]+$", row.strip()):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            tag = "th" if tbl == "" else "td"
            tbl += "<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>"
    if not tbl:
        return ""
    return (
        '<details class="cross"><summary>信源对照 / Source Cross-check（乌方 UA · 俄方 RU · 第三方 THIRD）</summary>'
        f'<div class="box"><table>{tbl}</table></div></details>'
    )


# ---------------------------------------------------------------------------
# 页面骨架模板（占位符 __XXX__ 替换，避免 % 格式化转义问题）
# ---------------------------------------------------------------------------

INDEX_HEAD = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-in">
    <h1>⚔️ 俄乌战争<span class="dot">·</span>每日情报</h1>
    <div class="sub">中英双语 · 乌俄与第三方信源交叉对照 · NATO 可信度分级 ｜ 更新：__UPDATED__</div>
    <nav>
      <a href="#map">🗺 态势地图</a>
      <a href="#today">📌 今日要点</a>
      <a href="#events">📊 事件检索</a>
      <a href="briefings.html">🗂 全部简报</a>
      <a href="map.html" target="_blank">⛶ 全屏地图</a>
    </nav>
  </div>
</div>
<div class="wrap">
  <div class="stats">
    __STATS__
  </div>

  <section class="sec" id="map">
    <div class="sec-h">
      <h2>🗺 战场态势</h2>
      <span class="muted">俄控区 / 前一日对比线 / 当日事件热区（点击地图可开关图层）</span>
      <span class="sp"></span>
      <a class="btn red" href="map.html" target="_blank">打开全屏地图 ↗</a>
    </div>
    <iframe class="map-frame" src="map.html" loading="lazy"
      title="战场态势地图" referrerpolicy="no-referrer"></iframe>
  </section>

  <section class="sec" id="today">
    <div class="sec-h">
      <h2>📌 今日要点</h2>
      <span class="muted">__LATEST_DATE__ ｜ 点击条目展开详情</span>
      <span class="sp"></span>
      <a class="btn" href="__LATEST_REL__">查看完整简报 ↗</a>
      <a class="btn" href="briefings.html">全部简报</a>
    </div>
    <div class="sec-b">
      __LATEST_BLOCK__
      __CROSSCHECK__
    </div>
  </section>

  <section class="sec" id="events">
    <div class="sec-h">
      <h2>📊 全部事件检索</h2>
      <span class="muted">共 <b id="cnt">0</b> 条匹配</span>
      <span class="sp"></span>
      <div class="filters">
        <input id="q" placeholder="搜索关键词 / search...">
        <select id="fType"><option value="">全部维度</option></select>
        <select id="fTheater"><option value="">全部战区</option></select>
      </div>
    </div>
    <div style="overflow-x:auto">
      <table class="ev">
        <thead><tr><th>日期</th><th>战区</th><th>维度</th><th>事件（中 / EN）</th><th>可靠</th><th>置信</th><th>来源方</th></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div class="morebar"><button id="more">加载更多 ↓</button></div>
  </section>

  <footer>
    非官方、开源、中立汇编，数据可能滞后或有误，仅供参考。原始数据：<a href="events.json">events.json</a>
    ｜ 简报：<a href="briefings.html">全部简报</a> ｜ 今日最新：<a href="__LATEST_REL__">最新简报</a>
    ｜ 态势地图：<a href="map.html">战场地图</a>
    ｜ 方法论：<a href="https://github.com/GTX950L/russia-ukraine-intel/tree/main/references">references/</a>
  </footer>
</div>
<script>
const TYPE_ZH = __TYPE_ZH__;
const THEATER_ZH = __THEATER_ZH__;
const PAGE = 50;
const tbody = document.getElementById('tbody');
const q = document.getElementById('q');
const fType = document.getElementById('fType');
const fTheater = document.getElementById('fTheater');
const cntEl = document.getElementById('cnt');
const moreBtn = document.getElementById('more');
let EVENTS = [];
let cur = PAGE;
function uniq(a){ return [...new Set(a)].filter(Boolean); }
fetch('events.json').then(r=>r.json()).then(data=>{
  EVENTS = data;
  uniq(EVENTS.map(e=>e.event_type)).forEach(t=>{ const o=document.createElement('option'); o.value=t; o.textContent=(TYPE_ZH[t]||t); fType.appendChild(o); });
  uniq(EVENTS.map(e=>e.theater)).forEach(t=>{ const o=document.createElement('option'); o.value=t; o.textContent=(THEATER_ZH[t]||t); fTheater.appendChild(o); });
  render();
}).catch(()=>{ cntEl.textContent = '数据加载失败'; });
function filtered(){
  const kw=q.value.trim().toLowerCase(), ft=fType.value, fth=fTheater.value;
  return EVENTS.filter(e=>{
    if(ft && e.event_type!==ft) return false;
    if(fth && e.theater!==fth) return false;
    if(kw){ const hay=(e.title_zh+' '+e.title_en+' '+e.summary_zh+' '+e.summary_en+' '+(e.tags||'')).toLowerCase(); if(!hay.includes(kw)) return false; }
    return true;
  });
}
function render(){
  const rows = filtered();
  tbody.innerHTML = rows.slice(0, cur).map(e=>{
    const disc=(e.disagreement_flag||'').toLowerCase().startsWith('y');
    const tags=(e.tags||'').split(';').filter(Boolean).map(t=>'<span class="tag">'+t+'</span>').join('');
    return '<tr><td style="white-space:nowrap">'+(e.date||'')+'</td><td>'+(THEATER_ZH[e.theater]||e.theater||'')+'</td><td>'+(TYPE_ZH[e.event_type]||e.event_type||'')+'</td>'
      +'<td class="et"><b>'+(e.title_zh||'')+'</b><span class="en">'+(e.title_en||'')+'</span><span class="sum">'+(e.summary_zh||'')+'</span> '+tags+'</td>'
      +'<td><span class="rel rel-'+(e.reliability||'x')+'">'+(e.reliability||'')+'</span></td><td>'+(e.confidence||'')+'</td>'
      +'<td>'+(disc?'<span class="disc">⚠ 分歧</span>':(e.source_side||''))+'</td></tr>';
  }).join('') || '<tr><td colspan="7" class="empty">无匹配事件</td></tr>';
  cntEl.textContent = rows.length + ' / ' + EVENTS.length;
  moreBtn.style.display = rows.length > cur ? 'inline-block' : 'none';
}
q.addEventListener('input', render);
fType.addEventListener('change', render);
fTheater.addEventListener('change', render);
moreBtn.addEventListener('click', () => { cur += PAGE; render(); });
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
<title>__TITLE__ ｜ 简报</title>
<style>__CSS__</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-in">
    <h1>📄 __TITLE__</h1>
    <div class="sub"><a href="__ROOT__index.html">← 返回首页</a> ｜ <a href="__ROOT__briefings.html">全部简报</a> ｜ <a href="__ROOT__map.html">🗺 态势地图</a></div>
  </div>
</div>
<div class="wrap"><div class="sec"><div class="sec-b lb">__BODY__</div></div>
<footer class="wrap" style="padding:16px 0 0;border-top:1px solid var(--bd)">
  非官方、开源、中立汇编，仅供参考。<a href="__ROOT__index.html">返回首页</a>
</footer>
</div>
</body>
</html>
"""


ARCHIVE_PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>全部简报归档</title>
<style>__CSS__</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-in">
    <h1>🗂 全部简报归档</h1>
    <div class="sub"><a href="index.html">← 返回首页</a> ｜ <a href="map.html">🗺 态势地图</a> ｜ 共 __COUNT__ 份</div>
  </div>
</div>
<div class="wrap"><div class="archive">__BODY__</div></div>
</body>
</html>
"""


GROUP_LABELS = {
    "daily": "📰 每日快讯", "weekly": "📈 每周复盘",
    "monthly": "📚 每月深度", "yearly": "🧭 每年评估",
}

GROUP_ORDER = ("daily", "weekly", "monthly", "yearly")


def scan_briefings() -> list[dict]:
    """扫描 briefings/*/ 下的 md，返回按组排序的结构化列表。"""
    items: list[dict] = []
    for sub in GROUP_ORDER:
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
        depth = 3 if it["group"] == "daily" else 3
        root = "../" * depth  # docs/briefings/daily/xxx.html → ../../../
        html = (BRIEFING_PAGE
                .replace("__TITLE__", it["title"])
                .replace("__CSS__", CSS)
                .replace("__ROOT__", root)
                .replace("__BODY__", body))
        out = DOCS / "briefings" / it["group"] / (it["stem"] + ".html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    log(f"briefing pages rendered: {len(items)}")


def build_archive_html(items: list[dict]) -> str:
    """归档页主体：按组卡片网格列出全部简报链接。"""
    parts: list[str] = []
    for group in GROUP_ORDER:
        group_items = [i for i in items if i["group"] == group]
        if not group_items:
            continue
        lis = []
        for it in group_items:
            lis.append(
                f'<li><a href="briefings/{it["group"]}/{it["stem"]}.html">{it["title"]}</a>'
                f'<span class="d">{it["stem"]}</span></li>'
            )
        parts.append(
            f'<div class="ag"><div class="ag-h">{GROUP_LABELS[group]} <span style="color:#98a2b3;font-size:12px;font-weight:400">({len(group_items)})</span></div>'
            f'<ul>{"".join(lis)}</ul></div>'
        )
    return "\n".join(parts)


def build_latest_block(items: list[dict]) -> tuple[str, str]:
    """首页"今日要点"区块：取最新一份每日简报（无则回退其他组最新）→ 精简要点卡。"""
    dailies = [i for i in items if i["group"] == "daily"]
    pool = dailies or items
    if not pool:
        return "", ""
    latest = pool[0]  # 已按文件名倒序
    rel = f'briefings/{latest["group"]}/{latest["stem"]}.html'
    pts = points_block(latest["md"])
    cross = crosscheck_block(latest["md"])
    return pts, rel


def main() -> None:
    rows = read_events()
    cfg = load_config()
    title_zh = cfg["project"]["title_zh"]
    updated = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M +08:00")

    counter_type = Counter(r.get("event_type", "") for r in rows)
    counter_theater = Counter(r.get("theater", "") for r in rows)
    disagreements = sum(1 for r in rows if str(r.get("disagreement_flag", "")).lower().startswith("y"))
    dates = [r.get("date", "") for r in rows if r.get("date")]
    today_events = sum(1 for d in dates if d == (max(dates) if dates else ""))
    latest_date = max(dates) if dates else ""

    items = scan_briefings()
    latest_block, latest_rel = build_latest_block(items)
    cross = crosscheck_block(_latest_md(items))
    render_briefing_pages(items)

    stats = (
        f'<div class="card acc"><div class="ico">📊</div><div class="num">{len(rows)}</div><div class="lbl">事件总数</div></div>'
        f'<div class="card red"><div class="ico">🔥</div><div class="num">{today_events}</div><div class="lbl">今日事件（{latest_date}）</div></div>'
        f'<div class="card amber"><div class="ico">⚔️</div><div class="num">{disagreements}</div><div class="lbl">分歧事件</div></div>'
        f'<div class="card green"><div class="ico">🗂</div><div class="num">{len(counter_type)}</div><div class="lbl">维度覆盖</div></div>'
        f'<div class="card"><div class="ico">📍</div><div class="num">{len(counter_theater)}</div><div class="lbl">战区覆盖</div></div>'
        f'<div class="card"><div class="ico">📚</div><div class="num">{len(items)}</div><div class="lbl">简报份数</div></div>'
    )

    type_zh = {k: v[0] for k, v in TYPE_LABELS.items()}
    rows_sorted = sorted(rows, key=lambda r: r.get("date", ""), reverse=True)

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(
        (INDEX_HEAD
         .replace("__TITLE__", title_zh)
         .replace("__CSS__", CSS)
         .replace("__UPDATED__", updated)
         .replace("__STATS__", stats)
         .replace("__LATEST_BLOCK__", latest_block or '<p style="color:#98a2b3">暂无简报</p>')
         .replace("__CROSSCHECK__", cross)
         .replace("__LATEST_DATE__", latest_date)
         .replace("__LATEST_REL__", latest_rel or "briefings.html")
         .replace("__TYPE_ZH__", json.dumps(type_zh, ensure_ascii=False))
         .replace("__THEATER_ZH__", json.dumps(THEATER_ZH, ensure_ascii=False))),
        encoding="utf-8")
    (DOCS / "events.json").write_text(json.dumps(rows_sorted, ensure_ascii=False), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    (DOCS / "briefings.html").write_text(
        (ARCHIVE_PAGE
         .replace("__CSS__", CSS)
         .replace("__COUNT__", str(len(items)))
         .replace("__BODY__", build_archive_html(items))),
        encoding="utf-8")
    render_map_html(rows)
    log(f"pages rendered: {len(rows)} events, {len(items)} briefings -> docs/")


def _latest_md(items: list[dict]) -> str:
    """取最新一份每日简报的原始 md（供信源对照提取）。"""
    for i in items:
        if i["group"] == "daily":
            return i["md"]
    return items[0]["md"] if items else ""


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
    """汇总首屏地图数据（战线/城市/重镇/热区/事件精确点/事件明细），不含道路铁路村庄（按需加载）。"""
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

    # 事件明细（最近 48h）：供地图点击热区/地点时弹出事件列表
    events_detail = []
    for r in recent:
        events_detail.append({
            "date": r.get("date", ""),
            "theater": r.get("theater", ""),
            "type_zh": TYPE_LABELS.get(r.get("event_type", ""), (r.get("event_type", ""), ""))[0],
            "title_zh": (r.get("title_zh", "") or "")[:140],
            "title_en": (r.get("title_en", "") or "")[:140],
            "rel": r.get("reliability", ""),
            "conf": r.get("confidence", ""),
            "disc": str(r.get("disagreement_flag", "")).lower().startswith("y"),
        })

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M +08:00"),
        "control": control,
        "control_prev": control_prev,
        "cities": _load_static_json("cities.json"),
        "strongholds": _load_static_json("strongholds.json"),
        "event_areas": event_areas,
        "event_points": event_points,
        "events": events_detail,
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
  :root { --acc:#1a5fb4; --red:#c0392b; --mut:#667085; --bd:#e4e8ef; }
  html,body{margin:0;padding:0;height:100%;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1c2330}
  #map{position:absolute;inset:40px 0 0 0;background:#eef1f5}
  /* 顶部信息条 */
  #topbar{position:absolute;left:0;right:0;top:0;height:40px;background:#fff;border-bottom:1px solid var(--bd);
    display:flex;align-items:center;gap:12px;padding:0 14px;font-size:12.5px;z-index:1000;color:#3a4356}
  #topbar b{font-size:13.5px;white-space:nowrap}
  #topbar .m{color:var(--mut)}
  #topbar .sp{flex:1}
  #topbar a{color:var(--acc);text-decoration:none;white-space:nowrap}
  #topbar a:hover{text-decoration:underline}
  #topbar button{border:1px solid var(--bd);background:#fafbfc;border-radius:7px;padding:3px 10px;font-size:12px;
    color:var(--acc);cursor:pointer;white-space:nowrap}
  #topbar button:hover{background:#eaf1fb}
  /* 面板 */
  .panel{position:absolute;background:#fff;border:1px solid var(--bd);border-radius:12px;
    padding:10px 14px;font-size:12px;line-height:1.8;box-shadow:0 2px 10px rgba(23,33,60,.10)}
  #legend{left:14px;top:52px;z-index:999;max-width:200px}
  #meta{right:14px;bottom:14px;z-index:999;text-align:right;color:var(--mut);font-size:11px;background:rgba(255,255,255,.92)}
  .lg-grp{font-size:11px;color:var(--mut);font-weight:700;margin:8px 0 3px;letter-spacing:.5px}
  .lg-grp:first-child{margin-top:0}
  .lg{display:flex;align-items:center;gap:8px;white-space:nowrap;cursor:pointer;border-radius:6px;padding:2px 6px;margin:0 -6px}
  .lg:hover{background:#f2f6fb}
  .lg.off{opacity:.35}
  .sw{display:inline-block;width:16px;height:10px;border-radius:3px;flex:none}
  .swl{display:inline-block;width:16px;height:2px;flex:none}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex:none}
  #legend h3{margin:0 0 2px;font-size:13px;font-weight:700}
  #legend .hint{color:#98a2b3;font-size:11px;margin:0 0 2px}
  #legend a{color:var(--acc);text-decoration:none}
  #loading{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:1000;
    background:#fff;border:1px solid var(--bd);border-radius:10px;padding:10px 18px;font-size:13px;display:none;
    box-shadow:0 2px 10px rgba(23,33,60,.1)}
  #full{appearance:none}
  .evlist{max-height:250px;overflow:auto}
  .evlist .ev{padding:6px 0;border-bottom:1px solid #eef1f6}
  .evlist .ev:last-child{border-bottom:none}
  .evlist .ev .m{font-size:11px;color:var(--mut)}
</style>
</head>
<body>
<div id="topbar">
  <b>🗺 战场态势地图</b>
  <span class="m">快照 __SNAP_INFO__</span>
  <span class="m">｜ 事件 __EVENT_RANGE__ · <b>__EVENT_NUM__</b> 条</span>
  <span class="sp"></span>
  <button id="full">⛶ 全屏</button>
  <a href="index.html">首页</a>
  <a href="briefings.html">简报</a>
</div>
<div id="map"></div>
<div id="loading">正在加载图层…</div>
<div id="legend" class="panel">
  <h3>图例</h3>
  <div class="hint">点击条目可开关图层</div>
  <div class="lg-grp">控制区</div>
  <div class="lg on" data-layer="control"><span class="sw" style="background:#e24b4a;opacity:.45"></span>俄控区（当日）</div>
  <div class="lg on" data-layer="prev"><span class="swl" style="border-top:2px dashed #7f77dd"></span>前一日控制线</div>
  <div class="lg-grp">交通</div>
  <div class="lg on" data-layer="roads"><span class="swl" style="background:#8a93a6"></span>主要道路</div>
  <div class="lg on" data-layer="rail"><span class="swl" style="background:#333;border-top:2px solid #333"></span>铁路</div>
  <div class="lg-grp">地标</div>
  <div class="lg on" data-layer="cities"><span class="dot" style="background:#1a5fb4"></span>城市</div>
  <div class="lg on" data-layer="strongholds"><span class="dot" style="background:#a32d2d;width:11px;height:11px;clip-path:polygon(50% 0,100% 38%,82% 100%,18% 100%,0 38%)"></span>防御重镇</div>
  <div class="lg on" data-layer="hubs"><span class="dot" style="background:#d85a30;width:10px;height:10px;transform:rotate(45deg)"></span>交通枢纽</div>
  <div class="lg" data-layer="villages"><span class="dot" style="background:#b4b2a9"></span>村庄（缩放 9 级+）</div>
  <div class="lg-grp">事件</div>
  <div class="lg on" data-layer="events"><span class="dot" style="background:#e24b4a;border:2px solid #fff"></span>当日事件热区</div>
</div>
<div id="meta" class="panel">
  数据：DeepState 每日快照 + OSM(ODbL) + 情报标注<br>
  生成：__GEN_AT__<br>
  <a href="index.html">← 返回首页</a> ｜ <a href="briefings.html">简报</a>
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
const showInfo = (extra, pos) => { info.setPosition(pos); info.setContent('<div style="font-size:12.5px;max-width:300px;line-height:1.6">'+extra+'</div>'); info.open(); };
const LL = (p) => new TMap.LatLng(p[0], p[1]);
const EVENTS = MAP_DATA.events || [];
const relSpan = (r) => '<span class="rel rel-'+(r||'x')+'" style="display:inline-block;min-width:16px;text-align:center;font-size:10px;font-weight:700;border-radius:4px;padding:0 4px;color:#fff;background:'+({A:'#1e7d4f',B:'#1a5fb4',C:'#e08c2e',D:'#c0392b',E:'#7a1f14',F:'#4a4a4a'}[r]||'#9aa3b2')+'">'+(r||'')+'</span>';
function eventsList(evs, head){
  if(!evs.length) return '<div style="color:#98a2b3">无关联事件</div>';
  return '<div class="evlist">'+evs.map(e=>
    '<div class="ev"><span class="m">'+e.date+' · '+e.type_zh+'</span> '+relSpan(e.rel)+' '
    +(e.disc?'<span style="color:#c0392b;font-size:11px">⚠分歧</span>':'')
    +'<div><b>'+e.title_zh+'</b></div>'
    +'<div class="m">'+e.title_en+'</div></div>').join('')+'</div>';
}

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
  const big = new TMap.MarkerStyle({ width: 8, height: 8, anchor: { x: 4, y: 4 }, color: '#1a5fb4' });
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
/* 当日事件：战区热区 + 精确地点合并为一层；点击弹事件明细 */
{
  const geoms = [];
  const styles = {};
  if (MAP_DATA.event_areas && MAP_DATA.event_areas.length) {
    MAP_DATA.event_areas.forEach((a, i) => {
      const size = Math.min(12 + a.count, 26);
      styles['a'+i] = new TMap.MarkerStyle({ width: size, height: size, anchor: { x: size/2, y: size/2 }, color: '#e24b4a', borderWidth: 2, borderColor: '#fff' });
      const evs = EVENTS.filter(e => e.theater === a.key).slice(0, 8);
      geoms.push({ id: 'a'+i, styleId: 'a'+i, position: new TMap.LatLng(a.lat, a.lon),
        extra: '<b>'+a.zh+'</b>：当日 '+a.count+' 条事件<br><br>'+eventsList(evs, a.zh) });
    });
  }
  if (MAP_DATA.event_points && MAP_DATA.event_points.length) {
    MAP_DATA.event_points.forEach((p, i) => {
      styles['p'+i] = new TMap.MarkerStyle({ width: 12, height: 12, anchor: { x: 6, y: 6 }, color: '#ff5722', borderWidth: 2, borderColor: '#fff' });
      const names = p.names || [];
      const evs = EVENTS.filter(e => names.some(n => n && (e.title_zh.indexOf(n) !== -1 || e.title_en.toLowerCase().indexOf(n.toLowerCase()) !== -1))).slice(0, 8);
      geoms.push({ id: 'p'+i, styleId: 'p'+i, position: new TMap.LatLng(p.lat, p.lon),
        extra: '<b>事件地点：'+names.join(' / ')+'</b>（关联 '+p.count+' 条）<br><br>'+eventsList(evs, names.join(' / ')) });
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
    L.roads = new TMap.MultiPolyline({ map, styles: { r: new TMap.PolylineStyle({ color: '#8a93a6', lineWidth: 2 }) },
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
/* 全屏 */
document.getElementById('full').addEventListener('click', () => {
  if (!document.fullscreenElement) { document.documentElement.requestFullscreen().catch(()=>{}); }
  else { document.exitFullscreen().catch(()=>{}); }
});
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
        f"event_areas={len(md['event_areas'])} event_points={len(md['event_points'])} "
        f"events_detail={len(md['events'])} -> docs/")


if __name__ == "__main__":
    main()

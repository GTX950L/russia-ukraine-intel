<!--
周复盘写作提纲 v2 · 给维护者 / 接手 AI 用 / Weekly deep-analysis guide
用途 / Purpose: 本文件不被流水线读取，是"如何写周度深度解析"的指南。
数据层已由流水线生成在 briefings/weekly/{YYYY}-W{WW}.md，
请把解析写进该文件 `## AI 深度解析` 标题之后（流水线重生成会保留）。
写作后落位与插槽规则见 AGENTS.md §10。
-->

# 周复盘深度解析 · 写作提纲 / Weekly Deep-Analysis Brief

## 目录 / Contents
- [用途 / Purpose](#用途--purpose)
- [输入 / Inputs](#输入--inputs)
- [方法约束 / Rules](#方法约束--rules)
- [建议结构 / Structure](#建议结构--structure)
- [可直接粘贴的提示词 / Prompt](#可直接粘贴的提示词--prompt)

## 用途 / Purpose
把本周自动数据层转化为可读的周度分析；不重复罗列事件，只提炼趋势、对照信源、标注分歧。
Turn the auto-generated weekly data layer into a readable analysis — extract trends and disagreement, don't re-list events.

## 输入 / Inputs
- 自动数据层 / Data layer: `briefings/weekly/{YYYY}-W{WW}.md`（各维度分组 + 信源对照表）
- 原始数据 / Raw: `data/master/events.csv` 切片 `{date_start} ~ {date_end}`
- 数据层里的 ⚠分歧 行 = 本周最高价值议题，优先解读。

## 方法约束 / Rules（见 AGENTS.md §7）
- 中立、可溯源；不把推测当事实；不为任何一方做宣传。
- 任何结论须对应 `events.csv` 的 event_id 或来源 URL。
- 推断须标注信号 + 时间窗口 + 可信度（高/中/低）。
- 三方分歧并列呈现，不替读者下结论。

## 建议结构 / Structure（中英双语）
1. **本周态势综述 / Weekly Overview** — 主线、转折点、与上周对比
2. **战线与装备要点 / Frontline & Equipment** — 提炼趋势，不罗列
3. **军政与外部动态 / Leadership & External**
4. **信源对照与关键分歧 / Cross-check & Disagreements** — 解释分歧意味着什么
5. **下周观察信号 / Watchlist** — 高价值观察点 + 触发条件
6. **数据快照 / Snapshot** — 本周事件数、分歧占比

## 可直接粘贴的提示词 / Copy-paste prompt
~~~~
你是俄乌战争开源情报汇编的编辑。请基于下面这份周度数据简报（已含乌/俄/第三方信源对照），
撰写"本周态势综述 / 战线与装备要点 / 军政与外部动态 / 信源对照与关键分歧 / 下周观察信号"五节，中英双语。
约束：中立可溯源、不把推测当事实、三方分歧并列呈现、推断须标可信度(高/中/低)。
只输出解析正文，不要重复数据层已有的事件列表。

=== 数据简报开始 ===
（把 briefings/weekly/{YYYY}-W{WW}.md 全文粘贴于此）
=== 数据简报结束 ===
~~~~

> 写好的解析粘回 `briefings/weekly/{YYYY}-W{WW}.md` 的 `## AI 深度解析` 之后（见 AGENTS.md §10）。

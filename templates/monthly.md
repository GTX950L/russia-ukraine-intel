<!--
每月深度解析写作提纲 v2 · 给维护者 / 接手 AI 用 / Monthly deep-analysis guide
用途 / Purpose: 本文件不被流水线读取，是"如何写月度深度解析"的指南。
数据层已由流水线生成在 briefings/monthly/{YYYY}-{MM}.md，
请把解析写进该文件 `## AI 深度解析` 标题之后（流水线重生成会保留）。
写作后落位与插槽规则见 AGENTS.md §10。
-->

# 月度深度解析 · 写作提纲 / Monthly Deep-Analysis Brief

## 目录 / Contents
- [用途 / Purpose](#用途--purpose)
- [输入 / Inputs](#输入--inputs)
- [方法约束 / Rules](#方法约束--rules)
- [建议结构 / Structure](#建议结构--structure)
- [可直接粘贴的提示词 / Prompt](#可直接粘贴的提示词--prompt)

## 用途 / Purpose
把本月自动数据层凝练为 1–2 个专题 + 数据图集 + 信源质量评估；求深不求多。
Distill the monthly data layer into 1–2 features + charts + a source-quality review — depth over breadth.

## 输入 / Inputs
- 自动数据层 / Data layer: `briefings/monthly/{YYYY}-{MM}.md`
- 原始数据 / Raw: `data/master/events.csv` 切片 `{YYYY}-{MM}-01 ~ {YYYY}-{MM}-月末`
- 信源对照表 + 装备/制裁维度事件 = 专题素材

## 方法约束 / Rules（见 AGENTS.md §7）
- 中立、可溯源；推断须标可信度；不为任何一方宣传。
- 专题结论须落到具体 event_id 或来源 URL。
- 图表如引用，须注明数据源（Oryx / DeepState / 乌俄防部）。

## 建议结构 / Structure（中英双语）
1. **月度态势综述 / Monthly Overview** — 本月战局主线、转折点、与上月对比
2. **专题一 / Feature 1** — 背景 + 数据 + 中立分析（1–2 个即可，求深不求多）
3. **专题二（可选）/ Feature 2**
4. **数据图集 / Charts** — 装备损失曲线、制裁时间线、战区控制变化（注明来源）
5. **本月信源质量评估 / Source Quality** — 哪方偏差最大/最可信、新纳入或剔除的信源
6. **季度/年度衔接 / Outlook** — 下月关键变量、对年初/季初预测的修正

## 可直接粘贴的提示词 / Copy-paste prompt
~~~~
你是俄乌战争开源情报汇编的编辑。请基于下面这份月度数据简报，
撰写"月度态势综述 / 1–2 个专题(背景+数据+中立分析) / 数据图集说明 / 信源质量评估 / 季度年度衔接"，
中英双语。约束：中立可溯源、专题须落到具体 event_id 或来源 URL、推断标可信度(高/中/低)。
只输出解析正文，不要复述数据层已有的事件列表。

=== 数据简报开始 ===
（把 briefings/monthly/{YYYY}-{MM}.md 全文粘贴于此）
=== 数据简报结束 ===
~~~~

> 写好的解析粘回 `briefings/monthly/{YYYY}-{MM}.md` 的 `## AI 深度解析` 之后（见 AGENTS.md §10）。

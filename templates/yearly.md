<!--
每年评估写作提纲 v2 · 给维护者 / 接手 AI 用 / Yearly assessment guide
用途 / Purpose: 本文件不被流水线读取，是"如何写年度评估"的指南。
数据层已由流水线生成在 briefings/yearly/{YYYY}.md，
请把解析写进该文件 `## AI 深度解析` 标题之后（流水线重生成会保留）。
写作后落位与插槽规则见 AGENTS.md §10。
-->

# 年度评估 · 写作提纲 / Yearly Assessment Brief

## 目录 / Contents
- [用途 / Purpose](#用途--purpose)
- [输入 / Inputs](#输入--inputs)
- [方法约束 / Rules](#方法约束--rules)
- [建议结构 / Structure](#建议结构--structure)
- [可直接粘贴的提示词 / Prompt](#可直接粘贴的提示词--prompt)

## 用途 / Purpose
对全年做一次诚实的战局复盘与预测回溯；命中、偏差、失效都要写，并给偏差原因。
Produce an honest annual review: hits, misses, and broken assumptions — with reasons for each.

## 输入 / Inputs
- 自动数据层 / Data layer: `briefings/yearly/{YYYY}.md`
- 原始数据 / Raw: `data/master/events.csv` 全年切片 `{YYYY}-01-01 ~ {YYYY}-12-31`
- 全年 monthly 简报 = 月度主线的纵向素材

## 方法约束 / Rules（见 AGENTS.md §7）
- 中立、可溯源；不为任何一方宣传；推断须标可信度。
- 预测复盘要诚实：命中/偏差/失效都要写，并给偏差原因。
- 情景概率用 高/中/低，且每条须有可观察的触发信号。

## 建议结构 / Structure（中英双语）
1. **全年综述 / Year in Review** — 战略态势、重大战役、外交转折、经济制裁、关键人物
2. **年初预测复盘 / Forecast Retrospective** — 表格：年初推测 | 结果 | 偏差分析 | 教训
3. **数据年鉴 / Annual Data** — 全年事件数、分歧占比、装备损失年度对比、制裁累计、信源可靠性年度变化
4. **下年情景 / Scenarios for {YYYY+1}** — 表格：情景 | 触发条件 | 概率 | 关键观察信号
5. **方法论年度检讨 / Methodology Audit** — 置信度标注一致性、长期缺第三方信源的维度、schema 修订需求

## 可直接粘贴的提示词 / Copy-paste prompt
~~~~
你是俄乌战争开源情报汇编的编辑。请基于下面这份年度数据简报，
撰写"全年综述 / 年初预测复盘(表格) / 数据年鉴 / 下年情景(表格,概率高/中/低+触发信号) / 方法论年度检讨"，
中英双语。约束：中立可溯源、预测复盘须诚实标注命中与偏差并给原因、情景须有可观察触发信号。
只输出解析正文，不要复述数据层已有的事件列表。

=== 数据简报开始 ===
（把 briefings/yearly/{YYYY}.md 全文粘贴于此）
=== 数据简报结束 ===
~~~~

> 写好的解析粘回 `briefings/yearly/{YYYY}.md` 的 `## AI 深度解析` 之后（见 AGENTS.md §10）。

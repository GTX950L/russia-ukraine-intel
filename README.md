# 俄乌战争每日情报 / Russia-Ukraine War Daily Intelligence

> 中英双语 · 乌俄与第三方信源交叉对照 · NATO 可信度分级 · 全自动流水线

一个面向长期维护的开放情报（OSINT）跟踪项目：按时间轴记录俄乌战争的战线、兵力、装备、领导人言行、平民、外部势力、外交谈判、经济制裁、网络认知战、战略威慑，以及军事援助与武器交付、能源与关键基础设施、法律与战争罪、人道与难民，并对未来做有依据的推测。
**在线站点 / Live site**
- 📰 站点首页（最新每日简报）: https://gtx950l.github.io/russia-ukraine-intel/
- 🗂 简报归档（日 / 周 / 月 / 年）: https://gtx950l.github.io/russia-ukraine-intel/briefings.html
- 📊 原始数据（events.json）: https://gtx950l.github.io/russia-ukraine-intel/events.json
## 目录 / Contents

- [核心原则 / Core Principles](#核心原则--core-principles)
- [内容维度（16 板块）/ Coverage (16 sections)](#内容维度16-板块--coverage-16-sections)
- [更新节奏 / Update Cadence](#更新节奏--update-cadence)
- [仓库结构 / Repository Layout](#仓库结构--repository-layout)
- [文档地图 / Document Map](#文档地图--document-map)
- [如何工作（全自动）/ How It Works](#如何工作全自动--how-it-works)
- [本地运行 / Local Setup](#本地运行--local-setup)
- [贡献 / Contributing](#贡献--contributing)
- [免责声明 / Disclaimer](#免责声明--disclaimer)

## 核心原则 / Core Principles

1. **中立、可溯源、可核查 / Neutral, traceable, verifiable** — 记录者姿态，不站队；每条关键事实附来源、标可信度，不把推测当事实。
2. **引用聚合，不重造轮子 / Aggregate, don't re-collect** — 硬数据（前线地图、装备损失、伤亡）直接引用 VIINA / DeepState / Oryx / ISW / Petro Ivaniuk 等权威 OSINT 源，**不自行采集战场原始数据**；本项目的增量价值在双语叙述 + 信源交叉对照 + 多周期分析 + 方法论透明。
3. **单一可信源 / Single Source of Truth** — `data/master/events.csv` 是全部内容的权威；简报与网站都从它派生。
4. **全自动流水线 / Fully automated pipeline** — 采集 → 解析 → 生成 → 校验 → 渲染 → 发布，由 GitHub Actions 定时驱动（见 `.github/workflows/daily.yml`）。
5. **可信度分级贯穿始终 / Reliability grading everywhere** — 每条事件标注 NATO 来源可靠性 A–F 与信息置信度 1–6；乌俄说法分歧时专设记录（**分歧本身就是情报**）。

## 内容维度（16 板块）/ Coverage (16 sections)

与 `templates/daily.md` 的章节一一对应，也对应 `scripts/utils.py` 中的 `TYPE_LABELS`（15 类事件）+ 自动生成的「信源对照」板块。
Maps to the sections in `templates/daily.md` and to `TYPE_LABELS` in `scripts/utils.py` (15 event types) plus the auto-generated *Source Cross-check* section.

| # | 板块 / Section | 对应 event_type |
|---|------|------|
| 1 | 战线状况 / Frontline | `frontline` |
| 2 | 兵力状况 / Troops & Manpower | `troops` |
| 3 | 装备状况 / Equipment | `equipment` |
| 4 | 军政领导人言行 / Leadership | `leadership` |
| 5 | 平民状况 / Civilian | `civilian` |
| 6 | 外部势力言行 / External Actors | `external` |
| 7 | 外交谈判 / Diplomacy | `diplomacy` |
| 8 | 经济与制裁 / Economy & Sanctions | `economy` |
| 9 | 网络/电子/认知战 / Cyber, Electronic & Cognitive | `cyber` |
| 10 | 战略威慑（核态势）/ Strategic Deterrence | `deterrence` |
| 11 | 军事援助与武器交付 / Military Aid & Arms Deliveries | `aid` |
| 12 | 能源与关键基础设施 / Energy & Critical Infrastructure | `energy` |
| 13 | 法律与战争罪 / Law of Armed Conflict / War Crimes | `law` |
| 14 | 人道与难民 / Humanitarian & Refugees | `humanitarian` |
| 15 | 信源对照 / Source Cross-check | 自动（有分歧或双方信源时） |
| 16 | 未来推测 / Forecast | `forecast` |

## 更新节奏 / Update Cadence

| 节奏 / Cadence | 产物 / Artifact | 说明 / Notes |
|------|------|------|
| 每日快讯 / Daily | `briefings/daily/YYYY-MM-DD.md` | 短、结构化、机器可读 / Short, structured, machine-readable |
| 周末复盘 / Weekly | `briefings/weekly/YYYY-Www.md` | 趋势 + 信源对照 / Trends + source cross-check |
| 每月深度 / Monthly | `briefings/monthly/YYYY-MM.md` | 专题 + 数据图 / Features + charts |
| 每年评估 / Yearly | `briefings/yearly/YYYY.md` | 全年战局 + 预测复盘 / Annual review + forecast retrospective |

## 仓库结构 / Repository Layout

```
data/master/events.csv   单一可信源（每条事实一行）/ Single source of truth
data/raw/                采集层落地的原始外源（按日期归档）/ Raw fetched sources
data/seed/               维护者手工补录的结构化事件（CSV，同 schema）/ Hand-curated seed events
data/vocab.yaml          受控词表（战区/类型/来源方/评级）/ Controlled vocabulary
scripts/                 自动化脚本 / Automation (fetch · normalize · build · render · validate)
templates/               日/周/月/年 双语简报模板与写作提纲 / Bilingual briefing templates & guides
references/              方法论：可信度量表 / 信源册 / 战区标签 / Methodology references
briefings/               生成的简报（派生产物）/ Generated briefings (derived)
docs/                    GitHub Pages 站点（由 render_pages.py 生成，.nojekyll）/ Static site
.github/workflows/       定时流水线 / Scheduled pipeline
config.yaml             全局配置（信源清单、生成参数）/ Global config
SCHEMA_VERSION          主事件表 schema 版本 / Schema version
```

## 文档地图 / Document Map

| 文档 / Document | 读者 / Audience | 用途 / Purpose |
|------|------|------|
| `README.md` | 人类读者 / Humans | 项目是什么、怎么用 / What & how |
| `AGENTS.md` | AI 代理 / AI agents | 如何安全操作仓库 / How to operate the repo safely |
| `templates/daily.md` | 流水线参考 / Pipeline reference | 每日快讯骨架与 12 板块定义 / Daily skeleton & 12-section spec |
| `templates/weekly.md` · `monthly.md` · `yearly.md` | 维护者 + 接手 AI | 深度解析写作提纲与提示词 / Deep-analysis guides & prompts |
| `references/confidence_rubric.md` | 所有贡献者 / All contributors | 可靠性 A–F 与置信度 1–6 定义 / Reliability & confidence definitions |
| `references/source_catalog.md` | 所有贡献者 / All contributors | 信源清单与取舍 / Source list & trade-offs |
| `references/theater_tags.md` | 所有贡献者 / All contributors | 战区受控标签 / Controlled theater tags |
| `config.yaml` | 维护者 + 流水线 / Maintainer + pipeline | 信源与生成参数 / Sources & pipeline params |

## 如何工作（全自动）/ How It Works

```
定时触发 → ①采集 fetch_sources → ②解析 normalize → ③撰写 build_briefing
        → ④校验 validate(CI) → ⑤渲染 render_pages → ⑥提交并发布 Pages
```

- 前 5 步全自动；`validate.py` 是自动质量闸（缺字段 / 非法词表 / 分歧无说明则失败阻断）。
- 维护者角色：周期性抽查、在 `config.yaml` 启用已验证的信源、必要时在 `data/seed/` 补录权威事件。

## 本地运行 / Local Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows；macOS/Linux 用: source .venv/bin/activate
pip install -r requirements.txt
python scripts/normalize.py        # 合并 raw/seed → events.csv
python scripts/build_briefing.py   # 生成当日简报（可加 --week / --month / --year）
python scripts/render_pages.py     # 生成 docs/ 站点
python scripts/validate.py         # 校验（CI 同款）
```

## 贡献 / Contributing

1. fork → 在 `data/seed/` 放一份同 schema 的 CSV（或从 `data/master/events.csv` 追加行）。
2. 每条事件必须带 `reliability`(A–F) 与 `confidence`(1–6)，分歧须填 `disagreement_note_zh`。
3. 提 PR，CI 校验通过后由维护者合并，自动重新发布。

> 详细操作与安全约束见 `AGENTS.md` / See `AGENTS.md` for detailed operating rules.

## 免责声明 / Disclaimer

本项目为**非官方、开源、中立**的信息汇编，数据可能滞后、有误或受信息战影响。所有结论仅供参考，不构成任何行动建议。引用内容版权归原信源所有。

---
维护者：GTX950L ｜ Schema：`SCHEMA_VERSION` ｜ 许可：CC BY 4.0（内容）/ MIT（代码）

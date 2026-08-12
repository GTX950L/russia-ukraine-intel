# 俄乌战争每日情报 / Russia-Ukraine War Daily Intelligence

> 中英双语 · 乌俄与第三方信源交叉对照 · NATO 可信度分级 · 全自动流水线

一个面向长期维护的开放情报（OSINT）跟踪项目：按时间轴记录俄乌战争的战线、兵力、装备、领导人言行、平民、外部势力、外交谈判、经济制裁、网络认知战、战略威慑，并对未来做有依据的推测。

## 🚀 快速入口

| 入口 | 链接 |
|------|------|
| 📰 **当日最新情报**（站点首页，自动展示最新一份每日简报） | https://gtx950l.github.io/russia-ukraine-intel/ |
| 🗂 **全部内容综合页**（事件时间线 + 搜索/维度/战区筛选） | https://gtx950l.github.io/russia-ukraine-intel/ |
| 📚 **简报归档**（日 / 周 / 月 / 年 全部简报渲染页） | https://gtx950l.github.io/russia-ukraine-intel/briefings.html |
| 📊 原始数据（events.json） | https://gtx950l.github.io/russia-ukraine-intel/events.json |

## 核心原则

1. **中立、可溯源、可核查**：记录者姿态，不站队；每条关键事实附来源，标可信度，不把推测当事实。
2. **引用聚合，不重造轮子**：硬数据（前线地图、装备损失、伤亡）直接引用 VIINA / DeepState / Oryx / ISW / Petro Ivaniuk 等权威 OSINT 源，**不自行采集战场原始数据**。本项目的增量价值在双语叙述 + 信源交叉对照 + 多周期分析 + 方法论透明。
3. **单一可信源**：`data/master/events.csv` 是全部内容的权威；简报与网站都从它派生。
4. **全自动流水线**：采集 → 解析 → 生成 → 校验 → 渲染 → 发布，由 GitHub Actions 定时驱动（见 `.github/workflows/daily.yml`）。
5. **可信度分级贯穿始终**：每条事件标注 NATO 来源可靠性 A–F 与信息置信度 1–6；乌俄说法分歧时专设记录（**分歧本身就是情报**）。

## 内容维度（12 项）

战线状况 · 兵力状况 · 装备状况 · 军政领导人言行 · 平民状况 · 外部势力言行 · 外交谈判 · 经济与制裁 · 网络/电子/认知战 · 战略威慑(核态势) · 信源对照 · 未来推测

## 更新节奏

| 节奏 | 产物 | 说明 |
|------|------|------|
| 每日快讯 | `briefings/daily/YYYY-MM-DD.md` | 短、结构化、机器可读 |
| 周末复盘 | `briefings/weekly/YYYY-Www.md` | 趋势 + 信源对照 |
| 每月深度 | `briefings/monthly/YYYY-MM.md` | 专题 + 数据图 |
| 每年评估 | `briefings/yearly/YYYY.md` | 全年战局 + 预测复盘 |

## 仓库结构

```
data/master/events.csv   单一可信源（每条事实一行）
data/raw/                采集层落地的原始外源（按日期归档）
data/seed/               维护者手工补录的结构化事件（CSV，同 schema）
data/vocab.yaml          受控词表（战区/类型/来源方/评级）
scripts/                 自动化脚本（fetch/normalize/build_briefing/render_pages/validate）
templates/               日/周/月/年 双语简报模板
references/              方法论：可信度量表 / 信源册 / 战区标签
briefings/               生成的简报（派生产物）
docs/                    GitHub Pages 站点（由 render_pages.py 生成，.nojekyll）
.github/workflows/       定时流水线
config.yaml             全局配置（信源清单、生成参数）
SCHEMA_VERSION          主事件表 schema 版本
```

## 如何工作（全自动）

```
定时触发 → ①采集 fetch_sources → ②解析 normalize → ③撰写 build_briefing
        → ④校验 validate(CI) → ⑤渲染 render_pages → ⑥提交并发布 Pages
```

- 前 5 步全自动；`validate.py` 是自动质量闸（缺字段/非法词表/分歧无说明则失败阻断）。
- 维护者角色：周期性抽查、在 `config.yaml` 启用已验证的信源、必要时在 `data/seed/` 补录权威事件。

## 本地运行

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python scripts/normalize.py        # 合并 raw/seed → events.csv
python scripts/build_briefing.py   # 生成当日简报
python scripts/render_pages.py     # 生成 docs/ 站点
python scripts/validate.py         # 校验（CI 同款）
```

## 贡献

1. fork → 在 `data/seed/` 放一份同 schema 的 CSV（或从 `data/master/events.csv` 追加行）。
2. 每条事件必须带 `reliability`(A–F) 与 `confidence`(1–6)，分歧须填 `disagreement_note_zh`。
3. 提 PR，CI 校验通过后由维护者合并，自动重新发布。

## 免责声明

本项目为**非官方、开源、中立**的信息汇编，数据可能滞后、有误或受信息战影响。所有结论仅供参考，不构成任何行动建议。引用内容版权归原信源所有。

---
维护者：GTX950L ｜ Schema：`SCHEMA_VERSION` ｜ 许可：CC BY 4.0（内容）/ MIT（代码）

# 可信度量表 / Confidence & Reliability Rubric

> 用途 / Purpose: 定义每条事件必须标注的两项评级（来源可靠性、信息置信度），供人工与 `validate.py` 共同校验。
> Defines the two ratings required on every event, used by both humans and `validate.py`.

**相关文档 / Related**
- 战区标签 → `theater_tags.md` ｜ 信源册 → `source_catalog.md`
- 字段约束总表 → `AGENTS.md` §3 ｜ 立场与安全 → `AGENTS.md` §7

## 目录 / Contents
- [一、来源可靠性（NATO A–F）](#一来源可靠性nato-af)
- [二、信息置信度（1–6）](#二信息置信度16)
- [三、本项目自增字段](#三本项目自增字段)
- [四、标注纪律](#四标注纪律)

## 一、来源可靠性（NATO 标准，A–F）/ Source Reliability

| 等级 / Level | 含义 / Meaning | 典型来源 / Typical sources |
|------|------|----------|
| A | 完全可靠 / Completely reliable | Oryx（影像确认）、官方原始文件、学术机构 |
| B | 通常可靠 / Usually reliable | VIINA、DeepState、主流媒体、研究机构 |
| C | 大体可靠 / Fairly reliable | 双方官方战报、多数媒体 |
| D | 通常不可靠 / Usually unreliable | 社媒匿名、未证实爆料 |
| E | 可靠性未知 / Reliability unknown | 新源、无法交叉验证 |
| F | 无法使用 / Cannot be used | 明显造假、摆拍、已被证伪 |

## 二、信息置信度（1–6，1=已确认，6=无法评估）/ Information Confidence

| 等级 / Level | 含义 / Meaning |
|------|------|
| 1 | 已确认（多源/影像佐证）/ Confirmed (multi-source or imagery) |
| 2 | 极可能（2+ 独立源）/ Highly probable (2+ independent sources) |
| 3 | 可能（单方源但合理）/ Possible (single plausible source) |
| 4 | 可疑（源弱或有矛盾）/ Doubtful (weak or conflicting source) |
| 5 | 猜测（无直接证据）/ Speculative (no direct evidence) |
| 6 | 无法评估 / Not assessable |

## 三、本项目自增字段 / Project-specific fields

- `source_side`：事件主要来源方 `ua` / `ru` / `third`（第三方/独立）。
- `disagreement_flag`：乌俄说法是否冲突。`yes` 时必须填 `disagreement_note_zh` 说明分歧点——**分歧本身是高质量情报**。
- `forecast_related`：该事件是否关联"未来推测"。

## 四、标注纪律 / Labeling discipline

- 置信度 ≤ 2 的关键事实，至少需一个可核实来源（URL 或第三方源）。
- 单方源（仅 ua 或仅 ru）的 events，默认置信度不高于 3；若要更高，须在 `disagreement_note_zh` 或摘要中说明为何采信。
- 推测（forecast）段每条必须写明：依据了哪几条信号 + 时间窗口（周/月）+ 可信度等级。

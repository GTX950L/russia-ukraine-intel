# 信源册 / Source Catalog

> 用途 / Purpose: 列出项目的信源取舍起点与分类；维护者按需增删，并在 `config.yaml` 同步登记。
> Lists the starting set of sources and how they are classified; maintainers extend it and register changes in `config.yaml`.

**相关文档 / Related**
- 可信度量表 → `confidence_rubric.md` ｜ 战区标签 → `theater_tags.md`
- 信源启用与核验 → `AGENTS.md` §6 ｜ 信源配置 → `config.yaml` 的 `sources`

**原则 / Principle**: 乌方 + 俄方 + 第三方独立源尽量凑齐，不做单一信源。下文为精选起点。
UA + RU + independent third-party sources should be combined wherever possible; avoid single-source claims.

## 目录 / Contents
- [第三方 / 独立（third）](#第三方--独立third)
- [乌方（ua）](#乌方ua)
- [俄方（ru）](#俄方ru)
- [使用约定](#使用约定)

## 第三方 / 独立（third）

| 信源 / Source | 类型 / Type | 可靠性 / Rel. | 说明 / Notes |
|------|------|--------|------|
| Oryx | 装备损失 | A | 逐条照片/视频确认，金标准（已停更但仍是基准） |
| VIINA | 多源事件数据 | B | 哈佛/乔治城学术级，GIS-ready CSV，乌+俄媒体双源 |
| DeepStateMap | 占领区地图 | B | 每日 GeoJSON，民间但被广泛引用 |
| ISW | 战争研究所日报 | A | 英文权威分析，含战场地图 |
| Bellingcat | 开源调查 | A | 调查报道、影像取证 |
| Petro Ivaniuk | 无人机/导弹 waves | B | 每日 CSV（CSIS 验证） |
| ukraine-war-analytics.com | OSINT 平台 | B | 最全汇总站（英文） |

## 乌方（ua）

| 信源 / Source | 类型 / Type | 可靠性 / Rel. | 说明 / Notes |
|------|------|--------|------|
| 乌克兰总参谋部 | 官方战报 | C | 日更，偏己方战果 |
| 乌克兰国防部 | 官方通报 | C | 装备/人员数据 |
| 总统府 / 总统发言人 | 领导人言行 | C | 政治表态 |

## 俄方（ru）

| 信源 / Source | 类型 / Type | 可靠性 / Rel. | 说明 / Notes |
|------|------|--------|------|
| 俄罗斯国防部 | 官方通报 | C | 日更，偏己方战果 |
| 俄总统新闻秘书(佩斯科夫) | 领导人言行 | C | 政治表态 |
| RIA / TASS | 官方媒体 | D | 宣传属性强，需交叉验证 |

## 使用约定 / Usage rules

- 每个关键事实在 `events.csv` 中尽量同时填 `source_ua` / `source_ru` / `source_third` 至少两类。
- 信源失效/被封是常态：在 `config.yaml` 置 `enabled:false` 并记录，采集失败不阻断流水线。
- 引用内容版权归原信源；本项目仅汇编、标注、链接，不主张原创。

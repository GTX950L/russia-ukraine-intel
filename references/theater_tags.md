# 战区标签词表 / Controlled Theater Tags

> 用途 / Purpose: 规定 `events.csv` 的 `theater` 字段合法取值；全库统一，否则无法检索/聚合。
> Defines the allowed values for the `theater` field; enforced repo-wide for consistent retrieval and aggregation.

**相关文档 / Related**
- 可信度量表 → `confidence_rubric.md` ｜ 信源册 → `source_catalog.md`
- 机器词表（唯一权威）→ `data/vocab.yaml` ｜ 字段总表 → `AGENTS.md` §3

**说明 / Note**: 下表与 `data/vocab.yaml` 保持一致；新增战区需在此登记并同步 `data/vocab.yaml`。
The table below mirrors `data/vocab.yaml`; new theaters must be registered in both places.

## 目录 / Contents
- [主战区（一级）](#主战区一级)
- [全局维度（不绑定具体战区）](#全局维度不绑定具体战区)
- [约定](#约定)

## 主战区（一级）/ Primary theaters

| 标签 / Tag | 中文 / ZH | 范围 / Scope |
|------|------|------|
| east-avdiivka | 东部-阿夫迪夫卡 | 阿夫迪夫卡及东南郊 |
| east-bakhmut | 东部-巴赫穆特 | 巴赫穆特/恰索夫亚尔 |
| east-donetsk | 东部-顿涅茨克 | 顿涅茨克州正面 |
| east-luhansk | 东部-卢甘斯克 | 卢甘斯克州正面 |
| south-kherson | 南部-赫尔松 | 第聂伯河两岸 |
| south-zaporizhzhia | 南部-扎波罗热 | 前线及核电站周边 |
| south-crimea | 南部-克里米亚 | 半岛及黑海西北 |
| north-kharkiv | 北部-哈尔科夫 | 哈尔科夫州正面 |
| border-kursk | 边境-库尔斯克 | 俄境内库尔斯克州乌占区 |
| black-sea | 黑海 | 舰队、粮食走廊、海上无人机 |
| homeland-ru | 俄本土 | 别尔哥罗德等纵深袭击 |
| homeland-ua | 乌纵深 | 基辅等后方空袭 |

## 全局维度（不绑定具体战区）/ Global dimensions

| 标签 / Tag | 中文 / ZH |
|------|------|
| political | 政治/全局 |
| economy | 经济/制裁 |
| cyber | 网络/认知 |
| deterrence | 战略威慑 |

## 约定 / Conventions

- 单条事件只标**一个主战区**；跨区用 `tags` 补充（如 `kherson;left-bank`）。
- 全局性维度（领导、外交、经济、网络、威慑）用上方 political/economy/cyber/deterrence。
- 地名英文标签与外源保持一致，便于引用与检索。

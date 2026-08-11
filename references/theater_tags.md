# 战区标签词表 / Controlled Theater Tags

`events.csv` 的 `theater` 字段**只能取下表值**（机器词表见 `data/vocab.yaml`），全库统一，否则无法检索/聚合。
新增战区需在此登记并同步 `data/vocab.yaml`。

## 主战区（一级）

| 标签 | 中文 | 范围 |
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

## 全局维度（不绑定具体战区）

| 标签 | 中文 |
|------|------|
| political | 政治/全局 |
| economy | 经济/制裁 |
| cyber | 网络/认知 |
| deterrence | 战略威慑 |

## 约定

- 单条事件只标**一个主战区**；跨区用 `tags` 补充（如 `kherson;left-bank`）。
- 全局性维度（领导、外交、经济、网络、威慑）用上方 political/economy/cyber/deterrence。
- 地名英文标签与外源保持一致，便于引用与检索。

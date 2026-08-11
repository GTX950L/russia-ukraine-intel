# AGENTS.md — 给接手本仓库的 AI 代理的操作手册 / Operating Manual for AI Agents

> 本文件是**给任何 AI 代理（Agent）看的引导说明**，不是给人看的 README。
> 当你（AI）被要求在本仓库执行任务时，**先读完本文件，再动任何文件**。
> 若本文件与 README.md 冲突，以本文件为准（本文件描述"如何安全地操作"，README 描述"项目是什么"）。

This file is the **boot instruction for any AI agent** working in this repo. Read it fully before touching anything. Where it conflicts with README.md, this file wins.

---

## 0. 一句话心智模型 / Mental Model

```
data/master/events.csv   ← 唯一可信源（Single Source of Truth），权威在此
        │  (派生 / derived)
        ├── briefings/daily|weekly|monthly|yearly/*.md   （由 build_briefing.py 生成）
        └── docs/  （站点，由 render_pages.py 生成，含 events.json）

data/seed/*.csv          ← 手工补录入口（与 events.csv 同 schema）
data/raw/*.csv           ← 采集层落地（信源适配器输出，目前信源默认禁用）
config.yaml / data/vocab.yaml / SCHEMA_VERSION  ← 机器可读的规则与版本
```

**铁律（数据层）**：不要手改 `briefings/` 里 `## AI 深度解析` 标题**之前**的内容，也不要手改 `docs/`——这些是派生文件，下次流水线会覆盖。
**例外（解析层）**：`briefings/weekly|monthly|yearly/*.md` 中 `## AI 深度解析` 标题**之后**的段落，由维护者或 AI 手写，流水线重生成时**保留不覆盖**。这就是"深度解析手动层"。
Rule: never hand-edit the data layer (above the `## AI 深度解析` sentinel) of briefings, nor `docs/`. The analysis layer below that sentinel in period briefings is yours to edit and is preserved across regenerations.

---

## 1. 如何新增一条事件 / How to add an event

两种方法，**二选一，不要混用造成重复**：

**方法 A（推荐，最稳）：放进 `data/seed/`**
- 新建 `data/seed/YYYY-MM-DD-<简短名>.csv`，表头与 `events.csv` 完全一致（见第 3 节字段表）。
- 不需要写 `event_id`——`normalize.py` 会自动编号；但如果你写了且不与现有冲突，会保留。
- 跑 `python scripts/normalize.py` 即合并进 `events.csv`。

**方法 B：直接追加到 `data/master/events.csv`**
- 用 **Python `csv` 模块或脚本**写，绝不手敲逗号（手动数逗号曾多次导致列错位：reliability/confidence 被串列）。
- 可参考 `scripts/_init_master.py` 思路，或直接用 pandas/stdlib csv。

> ⚠️ 受控字段约束：写 `theater` / `event_type` 前，先查 `data/vocab.yaml` 里的合法值。
> 非法值会被 `normalize.py` 回落到默认值（theater→political, event_type→external），信息就丢了。

---

## 2. 如何更新一条已存在的事件 / How to update an existing event

- **正确做法**：在 `data/master/events.csv` 里找到该 `event_id` 那一行，直接改那行的字段。
  `event_id` 是稳定主键，不要再建一行"修正版"。
- **不要**靠"在 seed 里放旧事件的新版本"来更新——当前去重按内容指纹，可能生成重复行。
- 改完跑 `python scripts/validate.py` 确认无违规。

---

## 3. 事件表字段表（24 列，顺序固定）/ Event schema (24 columns, fixed order)

```
event_id, date, theater, event_type, title_zh, title_en, summary_zh, summary_en,
source_side, source_ua, source_ru, source_third, url_ua, url_ru, url_third,
reliability, confidence, disagreement_flag, disagreement_note_zh,
forecast_related, tags, editor, updated_at, schema_version
```

关键约束（与 `validate.py` 一致）：
- `reliability` ∈ {A,B,C,D,E,F}（NATO 来源可靠性）；`confidence` ∈ {1..6}（信息置信度）。
  含义见 `references/confidence_rubric.md`。
- `disagreement_flag = yes` 时，**必须**填 `disagreement_note_zh`（否则 CI 失败）。
- `confidence ≤ 2`（高置信）时，**必须**至少带一个可核实来源（任一 URL 或 `source_third` 非空）。
- `source_side` ∈ {ua, ru, third}。`ua`=乌方，`ru`=俄方，`third`=独立第三方。
- 每条关键事实尽量凑齐 **乌 + 俄 + 第三方** 三类来源；歧见本身就是高价值情报。

---

## 4. 提交前必跑 / Pre-commit checklist

```bash
python scripts/normalize.py       # 若改了 seed 或 events.csv
python scripts/build_briefing.py  # 生成/刷新简报（可加 --date / --week / --month / --year）
python scripts/render_pages.py    # 刷新 docs/ 站点
python scripts/validate.py        # ← 必须 0 退出；否则不要提交
```

- `validate.py` 返回非 0 = 有违规 = **禁止提交**。CI 也会跑同款，失败会阻断合并。
- 不要提交 `docs/` 里的临时产物冲突；`docs/` 由流水线生成，但你本地预览时生成的也无害。

---

## 5. 流水线如何运行 / How the pipeline runs

- 由 `.github/workflows/daily.yml` 每日 **06:00 UTC** 定时触发，也可在 Actions 页手动 `workflow_dispatch`。
- 顺序：fetch_sources → normalize → build_briefing → validate(CI 闸) → render_pages → 提交并发布 Pages。
- **单信源失败不阻断**：`fetch_sources.py` 对单个源超时/报错会跳过并继续，不会让整条流水线挂掉。
- 发布站点：`https://gtx950l.github.io/russia-ukraine-intel/`（GitHub Pages，源 = main 分支 /docs）。

---

## 6. 信源开启义务 / Source-enable obligation

- `config.yaml` 里所有 `sources` 默认 `enabled: false`（因为 URL 需人工核验）。
- **在把某个源设为 `enabled: true` 之前，必须先确认其端点稳定可达、格式与 `parser` 匹配。**
- 不要凭直觉开启未核验的源；开启后第一次跑若报错，先回退 `enabled: false` 再排查。

---

## 7. 立场与安全 / Stance & safety

- **中立、可溯源、可核查**：记录者姿态，不站队；不把推测当事实。
- 推测类内容必须标注依据信号 + 时间窗口 + 可信度（见模板 `未来推测` 段）。
- 本项目为**非官方、开源、中立**汇编；结论仅供参考，不构成行动建议。
- 不要写入任何政治敏感定性、不要替任何一方做宣传性表述。

---

## 8. Schema 演进 / Schema evolution

- 主表 schema 版本号在仓库根 `SCHEMA_VERSION`（当前 `v1`）。
- **不要无声改动字段结构**。若要加列/改语义：先 bump `SCHEMA_VERSION`，写迁移说明，确保 `normalize.py`/`validate.py`/`build_briefing.py`/`render_pages.py` 同步适配，并在 PR 描述里说明迁移影响。

---

## 9. 给接手 AI 的最小上手步骤 / Quick start for a new agent

1. 读 `README.md`（项目是什么）+ 本文件（怎么操作）。
2. 读 `data/vocab.yaml`（合法战区/类型/评级）和 `references/confidence_rubric.md`（评级含义）。
3. 要加事件 → 用方法 A（seed CSV）或方法 B（直接改 events.csv，用代码写）。
4. 跑第 4 节的四条命令，`validate.py` 必须 0 退出。
5. 提交 PR；CI 校验通过即自动重新发布。

---

## 10. 深度解析手动层 / Manual deep-analysis layer

项目分工：**采集 + 结构化聚合全自动（流水线），深度解析由维护者或 AI 手动补写。**

- 流水线每晚 06:00 UTC 自动刷新 `events.csv` 与 `briefings/` 的**数据层**。
- 周/月/年简报末尾有 `## AI 深度解析` 插槽：该标题之后的内容**不被流水线覆盖**。
- 补写流程：
  1. 打开 `briefings/{weekly|monthly|yearly}/{对应文件}.md`，滚到 `## AI 深度解析` 之下。
  2. 读 `templates/{weekly|monthly|yearly}.md` 取结构提纲与**可直接粘贴的提示词**。
  3. 把该简报全文贴进提示词，交给任意 AI（或自己写），产出解析正文，粘回插槽。
  4. `git add` 该简报文件并提交即可（只需提交这一个文件，数据层由流水线管）。
- 注意：不要改 `## AI 深度解析` **之前**的数据层；那部分下次流水线会重写。

---
维护者：GTX950L ｜ 最后复核：2026-08-12 ｜ 本文件面向 AI 代理，随仓库长期维护。

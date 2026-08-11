"""公共工具：路径、配置、词表、CSV 读写、双语标签。

所有脚本均从仓库根目录以 `python scripts/xxx.py` 运行；本文件与脚本同目录，
`import utils` 即可（运行脚本时 scripts/ 会自动进入 sys.path）。
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MASTER = DATA / "master" / "events.csv"
VOCAB = DATA / "vocab.yaml"
CONFIG = ROOT / "config.yaml"
BRIEF = ROOT / "briefings"
DOCS = ROOT / "docs"
SEED = DATA / "seed"
RAW = DATA / "raw"

SCHEMA_VERSION = (ROOT / "SCHEMA_VERSION").read_text(encoding="utf-8").strip()

# 主事件表字段顺序（单一真相源 schema）
FIELDS = [
    "event_id", "date", "theater", "event_type",
    "title_zh", "title_en", "summary_zh", "summary_en",
    "source_side", "source_ua", "source_ru", "source_third",
    "url_ua", "url_ru", "url_third",
    "reliability", "confidence",
    "disagreement_flag", "disagreement_note_zh",
    "forecast_related", "tags", "editor", "updated_at", "schema_version",
]

# 维度中英标签（简报分组 + 站点展示共用）
TYPE_LABELS: dict[str, tuple[str, str]] = {
    "frontline": ("战线状况", "Frontline"),
    "troops": ("兵力状况", "Troops & Manpower"),
    "equipment": ("装备状况", "Equipment"),
    "leadership": ("军政领导人言行", "Leadership"),
    "civilian": ("平民状况", "Civilian"),
    "external": ("外部势力言行", "External Actors"),
    "diplomacy": ("外交谈判", "Diplomacy"),
    "economy": ("经济与制裁", "Economy & Sanctions"),
    "cyber": ("网络/电子/认知战", "Cyber, Electronic & Cognitive"),
    "deterrence": ("战略威慑(核态势)", "Strategic Deterrence"),
    "forecast": ("未来推测", "Forecast"),
}

THEATER_ZH: dict[str, str] = {
    "east-avdiivka": "东部-阿夫迪夫卡", "east-bakhmut": "东部-巴赫穆特",
    "east-donetsk": "东部-顿涅茨克", "east-luhansk": "东部-卢甘斯克",
    "south-kherson": "南部-赫尔松", "south-zaporizhzhia": "南部-扎波罗热",
    "south-crimea": "南部-克里米亚", "north-kharkiv": "北部-哈尔科夫",
    "border-kursk": "边境-库尔斯克", "black-sea": "黑海",
    "homeland-ru": "俄本土", "homeland-ua": "乌纵深",
    "political": "政治/全局", "economy": "经济/制裁",
    "cyber": "网络/认知", "deterrence": "战略威慑",
}


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_vocab() -> dict:
    return yaml.safe_load(VOCAB.read_text(encoding="utf-8"))


def read_events(path: Path = MASTER) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_events(rows: list[dict], path: Path = MASTER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def row_hash(r: dict) -> str:
    """去重指纹（忽略 event_id / updated_at）。"""
    base = "|".join(str(r.get(k, "")) for k in
                    ("date", "theater", "event_type", "title_en", "title_zh"))
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]


def new_event_id(date: str, seq: int) -> str:
    return f"{date}-{seq:03d}"


def log(msg: str) -> None:
    print(f"[ru-intel] {msg}")

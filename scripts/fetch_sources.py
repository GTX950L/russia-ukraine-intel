"""① 采集层：按 config.yaml 下载已启用的信源原始数据到 data/raw/。

设计要点：best-effort —— 单源失败只告警、不阻断流水线（信息战环境下信源常失效）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from utils import DATA, load_config, log

RAW = DATA / "raw"
TIMEOUT = 30


def main() -> None:
    cfg = load_config()
    RAW.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    any_ok = False
    for src in cfg.get("sources", []):
        name = src.get("name", "?")
        if not src.get("enabled"):
            log(f"skip (disabled): {name}")
            continue
        url = src.get("url")
        if not url:
            log(f"skip (no url): {name}")
            continue
        ext = src.get("format", "bin")
        dest = RAW / f"{name}_{today}.{ext}"
        try:
            log(f"fetching {name} -> {dest.name}")
            r = requests.get(
                url, timeout=TIMEOUT,
                headers={"User-Agent": "ru-intel-bot/1.0"},
            )
            r.raise_for_status()
            dest.write_bytes(r.content)
            any_ok = True
            log(f"  ok ({len(r.content)} bytes)")
        except Exception as e:  # noqa: BLE001 - 采集失败不得阻断流水线
            log(f"  FAILED {name}: {e}")
    log("fetch done" + ("" if any_ok else " (no source succeeded; pipeline continues)"))


if __name__ == "__main__":
    main()

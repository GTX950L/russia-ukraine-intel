"""① 采集层：按 config.yaml 下载已启用的信源原始数据到 data/raw/。

设计要点：best-effort —— 单源失败只告警、不阻断流水线（信息战环境下信源常失效）。

- 多数信源直接 GET url 落盘。
- dynamic: github-latest 的信源：先 GET GitHub 目录 API 取最新匹配文件，
  再下载其 download_url（用于文件名带日期、每日变动的源，如 DeepState 镜像）。
- 使用浏览器 UA，降低被 WAF(如 ISW 的 403) 直接拦截的概率。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

from utils import DATA, load_config, log

RAW = DATA / "raw"
TIMEOUT = 30

# 浏览器 UA，降低被站点 WAF 拦截概率（部分源对未知 UA 直接 403）
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


def _github_latest(listing_url: str, pattern: str) -> tuple[str, str] | None:
    """查询 GitHub 目录 API，返回 (最新匹配文件的 download_url, 源文件名)。

    返回源文件名以便调用方提取其中日期（如 deepstatemap_data_20260811），
    把数据日期写进 raw 文件名，供解析器读取。
    """
    try:
        r = requests.get(listing_url, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        items = r.json()
        pat = pattern.replace("*", ".*")
        matches = [it for it in items if re.search(pat, it.get("name", ""))]
        if not matches:
            log(f"  github-latest: 无匹配文件 (pattern={pattern})")
            return None
        matches.sort(key=lambda it: it.get("name", ""))
        last = matches[-1]
        return last.get("download_url"), last.get("name", "")
    except Exception as e:  # noqa: BLE001
        log(f"  github-latest resolve failed: {e}")
        return None


def main() -> None:
    cfg = load_config()
    RAW.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")  # 北京时间
    any_ok = False
    for src in cfg.get("sources", []):
        name = src.get("name", "?")
        if not src.get("enabled"):
            log(f"skip (disabled): {name}")
            continue
        base_url = src.get("url")
        if not base_url:
            log(f"skip (no url): {name}")
            continue
        # 动态解析最新文件（如日期戳文件名）
        file_date = today
        if src.get("dynamic") == "github-latest":
            res = _github_latest(base_url, src.get("pattern", "*"))
            if not res:
                continue
            real_url, src_name = res
            base_url = real_url
            dm = re.search(r"(\d{8})", src_name)
            if dm:
                file_date = dm.group(1)  # 用数据自带日期（如 20260811）
        ext = src.get("format", "bin")
        dest = RAW / f"{name}_{file_date}.{ext}"
        try:
            log(f"fetching {name} -> {dest.name}")
            r = requests.get(base_url, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            dest.write_bytes(r.content)
            any_ok = True
            log(f"  ok ({len(r.content)} bytes)")
        except Exception as e:  # noqa: BLE001 - 采集失败不得阻断流水线
            log(f"  FAILED {name}: {e}")
    log("fetch done" + ("" if any_ok else " (no source succeeded; pipeline continues)"))


if __name__ == "__main__":
    main()

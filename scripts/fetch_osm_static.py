"""一次性工具：从 OSM Overpass 拉取乌克兰静态地图数据，写入 data/map/static/。

产出（精简 JSON，供 render_pages.py 生成地图页使用）：
- cities.json    全乌克兰 city/town 点（name/place/lat/lon）
- villages.json  前线区域 village/hamlet 点（用于"与战场变化相关的小村庄"匹配）
- roads.json     东部战区 motorway/trunk/primary 道路（简化坐标）
- rail.json      东部战区铁路线

用法：python scripts/fetch_osm_static.py [--east-only]
说明：数据来自 OpenStreetMap（ODbL），仅作标注数据层，不作为底图。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "map" / "static"
# Overpass 公共实例（实测稳定性排序：mail.ru 最稳，主实例经常限流/超时）
APIS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# 前线相关区域分片（乌克兰东部战场范围）。
# 注意 Overpass bbox 顺序 = (south, west, north, east) = (lat_min, lon_min, lat_max, lon_max)
VILLAGE_BBOXES = {
    "donbas": (47.4, 36.5, 49.6, 39.3),          # 顿巴斯核心
    "zaporizhzhia": (46.0, 33.0, 48.2, 36.8),    # 扎波罗热/赫尔松
    "kharkiv": (48.4, 36.0, 50.6, 38.8),         # 哈尔科夫/库皮扬斯克
    "sumy": (50.4, 33.6, 52.4, 35.8),            # 苏梅/库尔斯克边境
}
EAST = (46.0, 33.0, 52.5, 40.3)                  # 东部战区（乌克兰范围）


_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "*/*"}


def pick_api() -> str:
    """快速探测（6s 连接/12s 读取）选一个当前可用的端点，避免每个大查询都去试所有端点。"""
    probe = '[out:json][timeout:8];node(50.0,30.0,50.05,30.05);out;'
    for api in APIS:
        try:
            r = requests.post(api, data={"data": probe}, headers=_HEADERS, timeout=(6, 12))
            if r.status_code == 200:
                print(f"  ✓ 选用端点: {api}", flush=True)
                return api
            print(f"  {api} -> HTTP {r.status_code}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {api} 不可用: {type(e).__name__}", flush=True)
    print("  ! 全部端点探测失败，退回第一个", flush=True)
    return APIS[0]


def q(data: str, timeout: int = 240, api: str | None = None) -> list:
    """连接超时 12s（避免失败时空等），读取超时 timeout；只打一个端点，最多重试 1 次。"""
    target = api or APIS[0]
    for attempt in range(2):
        try:
            r = requests.post(target, data={"data": data}, headers=_HEADERS,
                              timeout=(12, timeout))
            if r.status_code == 200:
                return r.json().get("elements", [])
            print(f"  {target} -> HTTP {r.status_code}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {target} 失败: {type(e).__name__}", flush=True)
    return []


def save(name: str, data) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  saved data/map/static/{name}: {len(data)} 条")


def fetch_cities(api: str) -> None:
    print("[1/4] 城市/镇 ...", flush=True)
    els = q('[out:json][timeout:90];node["place"~"^(city|town)$"](44.0,22.0,52.5,40.3);out;',
            api=api)
    pts = [{"n": e.get("tags", {}).get("name", ""),
            "p": e.get("tags", {}).get("place", ""),
            "lat": round(e["lat"], 4), "lon": round(e["lon"], 4)}
           for e in els if e.get("lat")]
    save("cities.json", pts)


def fetch_villages(api: str) -> None:
    print("[2/4] 前线村庄（分片）...", flush=True)
    all_pts = []
    for region, (s, w, n, e) in VILLAGE_BBOXES.items():
        print(f"  - {region} bbox({s},{w},{n},{e}) ...", flush=True)
        els = q(f'[out:json][timeout:90];'
                f'node["place"~"^(village|hamlet)$"]({s},{w},{n},{e});out;',
                api=api)
        pts = [{"n": e.get("tags", {}).get("name", ""),
                "lat": round(e["lat"], 4), "lon": round(e["lon"], 4)}
               for e in els if e.get("lat")]
        all_pts.extend(pts)
        print(f"    {len(pts)} 个", flush=True)
        time.sleep(3)  # 礼貌间隔，避免 Overpass 限流
    save("villages.json", all_pts)


def fetch_ways(key: str, value: str, api: str, bbox=EAST) -> list:
    """按 tag key~regex 拉取线要素（不落盘，由调用方合并保存）。"""
    s, w, n, e = bbox
    print(f"  {key}~{value} bbox({s},{w},{n},{e}) ...", flush=True)
    els = q(f'[out:json][timeout:240];way["{key}"~"{value}"]({s},{w},{n},{e});out geom;',
            timeout=300, api=api)
    out = []
    for w in els:
        g = w.get("geometry", [])
        tags = w.get("tags", {})
        if not g or len(g) < 2:
            continue
        out.append({
            "n": tags.get("name", "") or tags.get("ref", ""),
            "c": [[round(p["lat"], 4), round(p["lon"], 4)] for p in g],
        })
    return out


# 道路/铁路分片（避免单次重查询在公共 Overpass 上超时）
ROADS_BBOXES = [(46.0, 33.0, 52.5, 40.3)]           # 主干道单片即可（motorway+trunk）
RAIL_BBOXES = [(48.5, 33.0, 52.5, 40.3),            # 铁路拆南北两片
               (46.0, 33.0, 48.5, 40.3)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-cities", action="store_true")
    ap.add_argument("--skip-villages", action="store_true")
    ap.add_argument("--skip-roads", action="store_true")
    ap.add_argument("--skip-rail", action="store_true")
    args = ap.parse_args()
    api = pick_api()
    if not args.skip_cities:
        fetch_cities(api)
    if not args.skip_villages:
        fetch_villages(api)
    if not args.skip_roads:
        # primary 量极大易超时，先取 motorway+trunk（重要交通线），primary 后续需要时再补
        roads = []
        for bbox in ROADS_BBOXES:
            roads += fetch_ways("highway", "^(motorway|trunk)$", api, bbox=bbox)
        save("roads.json", roads)
    if not args.skip_rail:
        rail = []
        for bbox in RAIL_BBOXES:
            rail += fetch_ways("railway", "^(rail)$", api, bbox=bbox)
            time.sleep(3)
        save("rail.json", rail)
    print("done")


if __name__ == "__main__":
    main()

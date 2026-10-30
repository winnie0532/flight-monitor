"""讀取設定；每輪查詢前重新載入。"""
from datetime import date
import json
from pathlib import Path
import re


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("設定最外層必須是 JSON 物件")
    routes = config.get("routes")

    if not isinstance(routes, list) or not routes:
        raise ValueError("routes 必須是至少一組航線的清單")

    seen = set()

    for index, route in enumerate(routes, start=1):
        if not isinstance(route, dict):
            raise ValueError(f"第 {index} 組航線必須是 JSON 物件")

        for field in ("origin", "destination"):
            value = route.get(field)

            if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
                raise ValueError(
                    f"第 {index} 組的 {field} 必須是三碼大寫機場代碼"
                )

        if route["origin"] == route["destination"]:
            raise ValueError(f"第 {index} 組出發與抵達機場不可相同")

        departure = date.fromisoformat(route["departure_date"])

        if departure < date.today():
            raise ValueError(f"第 {index} 組出發日期不可早於今天")

        route.setdefault("return_date", None)

        if route["return_date"] is not None:
            if date.fromisoformat(route["return_date"]) < departure:
                raise ValueError(f"第 {index} 組回程不可早於出發日期")

        allowed = {"origin", "destination", "departure_date", "return_date"}

        if set(route) - allowed:
            raise ValueError(
                f"第 {index} 組只可填航線與日期，其他設定請放最外層"
            )

        key = tuple(
            route[k]
            for k in ("origin", "destination", "departure_date", "return_date")
        )

        if key in seen:
            raise ValueError(f"第 {index} 組航線與日期重複")

        seen.add(key)
    if config["currency"] != "TWD":
        raise ValueError("目前解析器只支援 TWD")
    defaults = {"interval_seconds": 600, "nonstop_only": True,
                "max_duration_minutes": 240, "browser_channel": "chrome",
                "min_wait_seconds": 15, "max_wait_seconds": 60,
                "stable_seconds": 8}
    for key, value in defaults.items():
        config.setdefault(key, value)
    for key, minimum in (("interval_seconds", 60), ("min_wait_seconds", 0),
                         ("max_wait_seconds", 1), ("stable_seconds", 1)):
        value = config[key]
        if type(value) is not int or value < minimum:
            raise ValueError(f"{key} 必須是至少 {minimum} 的整數")
    if config["max_wait_seconds"] < max(config["min_wait_seconds"], config["stable_seconds"]):
        raise ValueError("max_wait_seconds 不可小於 min_wait_seconds 或 stable_seconds")
    if type(config["nonstop_only"]) is not bool:
        raise ValueError("nonstop_only 請填 true 或 false")
    limit = config["max_duration_minutes"]
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("max_duration_minutes 請填正整數或 null")
    if config["browser_channel"] not in ("chrome", "msedge", "chromium"):
        raise ValueError("browser_channel 請填 chrome、msedge 或 chromium")
    return config

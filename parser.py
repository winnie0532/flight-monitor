"""解析英文 Google Flights 卡片，不進行歷史比價。"""
from datetime import datetime
from decimal import Decimal
import re

def parse_price(text):
    # 接受明確的新臺幣標記；不把一般 $ 當成 TWD。
    match = re.search(r"(?:NT\$|TWD)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?![0-9])", text)
    if not match:
        return None
    value = Decimal(match.group(1).replace(",", ""))
    return str(value) if value > 0 else None

def parse_flight(raw_text):
    text = raw_text.replace("\u202f", " ").replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 擷取前兩個 AM/PM 時間，以及抵達日的 +1、+2。
    times = list(re.finditer(
        r"(\d{1,2}:\d{2})\s*(AM|PM)(?:\s*\+(\d+))?",
        text,
        re.I,
    ))

    def to_24h(match):
        value = f"{match.group(1)} {match.group(2).upper()}"
        return datetime.strptime(value, "%I:%M %p").strftime("%H:%M")

    # 依目前英文卡片格式，航空公司在抵達時間之後、飛行時間之前。
    duration = re.search(
        r"\b(?:(\d+)\s*hr(?:s)?\s*)?(?:(\d+)\s*min)\b"
        r"|\b(\d+)\s*hr(?:s)?\b",
        text,
        re.I,
    )

    airline = None
    if len(times) >= 2 and duration:
        between = text[times[1].end():duration.start()].strip()
        airline = " / ".join(
            line.strip() for line in between.splitlines() if line.strip()
        ) or None

    duration_minutes = None
    if duration:
        hours = int(duration.group(1) or duration.group(3) or 0)
        minutes = int(duration.group(2) or 0)
        duration_minutes = hours * 60 + minutes

    stop_match = re.search(r"\b(\d+)\s+stops?\b", text, re.I)
    stops = (
        0 if re.search(r"\bNonstop\b", text, re.I)
        else int(stop_match.group(1)) if stop_match
        else None
    )

    co2 = re.search(r"([\d,]+(?:\.\d+)?)\s*kg\s*CO2e", text, re.I)

    return {
        "airline": airline,
        "departure_time": to_24h(times[0]) if times else None,
        "arrival_time": to_24h(times[1]) if len(times) >= 2 else None,
        "arrival_day_offset": (
            int(times[1].group(3) or 0) if len(times) >= 2 else None
        ),
        "duration_minutes": duration_minutes,
        "stops": stops,
        "co2_kg": float(co2.group(1).replace(",", "")) if co2 else None,
    }


def parse_cards(cards, config):
    rows = []
    seen = set()
    for card in cards:
        text = card.strip()
        normalized = re.sub(r"\s+", " ", text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        # 排除非航班清單項目，但保留無報價、欄位解析不完整的航班。
        if not re.search(r"\b\d{1,2}:\d{2}\b", text):
            continue
        if not re.search(r"\b(?:Nonstop|\d+ stops?)\b", text, re.I):
            continue
        row = {"raw_text": text, "currency": config["currency"]}
        try:
            row.update(parse_flight(text))
            row["price"] = parse_price(text)
            row["parse_status"] = (
                "ok" if all(row.get(k) is not None for k in
                ("airline", "departure_time", "arrival_time", "duration_minutes", "stops"))
                else "partial"
            )
            row["parse_error"] = None
        except (ValueError, TypeError) as exc:
            row.update(price=None, parse_status="error", parse_error=str(exc))
        row["price_status"] = (
            "available" if row["price"] is not None else
            "unavailable" if re.search(r"price unavailable", text, re.I) else "unparsed"
        )
        matches = True
        if config["nonstop_only"] and row.get("stops") != 0:
            matches = False
        limit = config["max_duration_minutes"]
        if limit is not None and (row.get("duration_minutes") is None or row["duration_minutes"] > limit):
            matches = False
        row["matches_filter"] = int(matches)
        rows.append(row)
    return rows

"""資料庫結構不符，請指定其他 DB 或執行 --reset-db"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    search_url TEXT NOT NULL,
    wait_reason TEXT,
    raw_card_count INTEGER NOT NULL,
    flight_count INTEGER NOT NULL,
    priced_count INTEGER NOT NULL,
    unavailable_count INTEGER NOT NULL,
    parse_problem_count INTEGER NOT NULL,
    matching_count INTEGER NOT NULL,
    error TEXT,
    raw_cards_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flight_prices (
    id INTEGER PRIMARY KEY,
    check_id INTEGER NOT NULL REFERENCES checks(id),
    checked_at TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    return_date TEXT,
    currency TEXT NOT NULL,
    price NUMERIC,
    price_status TEXT NOT NULL,
    airline TEXT,
    departure_time TEXT,
    arrival_time TEXT,
    arrival_day_offset INTEGER,
    duration_minutes INTEGER,
    stops INTEGER,
    co2_kg REAL,
    matches_filter INTEGER NOT NULL,
    parse_status TEXT NOT NULL,
    parse_error TEXT,
    raw_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flights_check ON flight_prices(check_id);
CREATE INDEX IF NOT EXISTS idx_flights_route_date
ON flight_prices(origin, destination, departure_date, checked_at);
"""


def connect(database):
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=30)
    connection.execute("PRAGMA foreign_keys=ON")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    has_tables = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()
    if version != 2 and has_tables:
        connection.close()
        raise ValueError("這是舊版或其他 DB，請使用新的檔名，或執行 --reset-db 備份重建")
    connection.executescript(SCHEMA)
    connection.execute("PRAGMA user_version=2")
    connection.commit()
    return connection


def reset_database(database):
    """明確指定重建時先備份，避免誤刪歷史。"""
    database = Path(database)
    backup = None
    if database.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = database.with_name(f"{database.stem}.backup-{stamp}{database.suffix}")
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        with sqlite3.connect(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for name in ("flight_prices", "checks"):
                connection.execute(f'DROP TABLE IF EXISTS "{name}"')
            connection.execute("PRAGMA user_version=0")
    connection = connect(database)
    connection.close()
    return backup


def record(database, config, started_at, url, cards, rows, wait_reason=None, error=None):
    connection = connect(database)
    try:
        with connection:
            counts = {
                "raw": len(cards), "flights": len(rows),
                "priced": sum(r["price"] is not None for r in rows),
                "unavailable": sum(r["price_status"] == "unavailable" for r in rows),
                "problems": sum(r["parse_status"] != "ok" or r["price_status"] == "unparsed" for r in rows),
                "matching": sum(r["matches_filter"] for r in rows),
            }
            status = "error" if error else "partial" if counts["problems"] or wait_reason == "timeout" else "ok"
            cursor = connection.execute("""INSERT INTO checks (
                checked_at,finished_at,status,config_json,search_url,wait_reason,
                raw_card_count,flight_count,priced_count,unavailable_count,
                parse_problem_count,matching_count,error,raw_cards_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                started_at, datetime.now(timezone.utc).isoformat(), status,
                json.dumps(config, ensure_ascii=False), url, wait_reason,
                counts["raw"],counts["flights"],counts["priced"],counts["unavailable"],
                counts["problems"],counts["matching"],error,json.dumps(cards, ensure_ascii=False)))
            check_id = cursor.lastrowid
            for row in rows:
                item = {"check_id":check_id,"checked_at":started_at,
                        **{key:config[key] for key in
                           ("origin","destination","departure_date","return_date","currency")},
                        **row}
                columns = ",".join(item)
                connection.execute(
                    f"INSERT INTO flight_prices ({columns}) VALUES ({','.join('?' for _ in item)})",
                    tuple(item.values()))
        return check_id, counts
    finally:
        connection.close()

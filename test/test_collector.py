import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from config import load_config
from parser import parse_cards
from monitor import run_once
from storage import connect, record, reset_database

ROOT = Path(__file__).resolve().parent
CARD = "2:15 PM\n – \n5:55 PM\nTransNusa\n3 hr 40 min\nSIN–DPS\nNonstop\n–\nNT$3,188"


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.json")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "collection.sqlite3"

    def test_parse_fields(self):
        row = parse_cards([CARD], self.config)[0]
        self.assertEqual((row["airline"],row["departure_time"],row["arrival_time"]),
                         ("TransNusa","14:15","17:55"))
        self.assertEqual(row["duration_minutes"],220)
        self.assertEqual(row["stops"],0)
        self.assertIsNone(row["co2_kg"])
        self.assertEqual(row["price"],"3188")

    def test_overnight(self):
        row = parse_cards([CARD.replace("2:15 PM", "9:15 PM").replace("5:55 PM", "12:05 AM+1")], self.config)[0]
        self.assertEqual(row["arrival_day_offset"],1)
        self.assertEqual(row["arrival_time"],"00:05")

    def test_unavailable_and_filter_preserved(self):
        cards = [CARD.replace("NT$3,188","Price unavailable"), CARD.replace("Nonstop","1 stop")]
        rows = parse_cards(cards,self.config)
        self.assertEqual(len(rows),2)
        self.assertIsNone(rows[0]["price"])
        self.assertEqual(rows[0]["price_status"],"unavailable")
        self.assertEqual(rows[1]["matches_filter"],0)

    def test_limit_marks_instead_of_deletes(self):
        self.config["max_duration_minutes"] = 200
        row = parse_cards([CARD],self.config)[0]
        self.assertEqual(row["matches_filter"],0)

    def test_dedup_and_unrelated(self):
        rows = parse_cards([CARD,CARD.replace(" ","\u202f"),"Hotels NT$100"],self.config)
        self.assertEqual(len(rows),1)

    def test_ambiguous_currency(self):
        row = parse_cards([CARD.replace("NT$3,188","$3,188")],self.config)[0]
        self.assertIsNone(row["price"])
        self.assertEqual(row["price_status"],"unparsed")

    def test_history_and_missing_prices(self):
        cards = [CARD, CARD.replace("NT$3,188","Price unavailable")]
        rows = parse_cards(cards,self.config)
        for _ in range(2):
            _, counts = record(self.db,self.config,"2026-10-29T07:00:00+00:00","test",cards,rows,"stable")
        self.assertEqual(counts["priced"],1)
        self.assertEqual(counts["unavailable"],1)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM flight_prices").fetchone()[0],4)
            self.assertEqual(c.execute("SELECT count(*) FROM flight_prices WHERE price IS NULL").fetchone()[0],2)
            self.assertEqual(c.execute("SELECT count(*) FROM checks").fetchone()[0],2)
            self.assertNotIn("lowest_price",[r[1] for r in c.execute("PRAGMA table_info(checks)")])

    def test_fetch_failure_recorded(self):
        with patch("monitor.fetch_cards",side_effect=RuntimeError("offline")):
            self.assertEqual(run_once(self.config,self.db),1)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT status,flight_count FROM checks").fetchone(),("error",0))

    def test_collection_pipeline_without_browser(self):
        result = {"cards":[CARD],"url":"test","wait_reason":"stable"}
        with patch("monitor.fetch_cards",return_value=result):
            self.assertEqual(run_once(self.config,self.db),0)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT airline,price FROM flight_prices").fetchone(),("TransNusa",3188))

    def test_old_schema_refused_and_backed_up(self):
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE checks(id INTEGER PRIMARY KEY, lowest_price TEXT)")
            c.execute("INSERT INTO checks VALUES(1,'123')")
        with self.assertRaises(ValueError):
            connect(self.db)
        backup = reset_database(self.db)
        with sqlite3.connect(backup) as c:
            self.assertEqual(c.execute("SELECT lowest_price FROM checks").fetchone()[0],"123")
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM checks").fetchone()[0],0)

    def test_invalid_config_and_reload(self):
        path = Path(self.tmp.name) / "config.json"
        c = dict(self.config)
        c["interval_seconds"] = 600
        path.write_text(json.dumps(c))
        self.assertEqual(load_config(path)["interval_seconds"],600)
        c["interval_seconds"] = 300
        path.write_text(json.dumps(c))
        self.assertEqual(load_config(path)["interval_seconds"],300)
        c["nonstop_only"] = "true"
        path.write_text(json.dumps(c))
        with self.assertRaises(ValueError):
            load_config(path)


if __name__ == "__main__":
    unittest.main()

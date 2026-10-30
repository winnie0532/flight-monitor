"""機票資料收集器：讀設定 → 抓卡片 → 解析 → 存檔。"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

from config import load_config
from parser import parse_cards
from scraper import fetch_cards, search_url
from storage import connect, record, reset_database

ROOT = Path(__file__).resolve().parent


def run_once(config, database, headed=False, pause=False):
    started = datetime.now(timezone.utc).isoformat()
    url, cards, rows, reason, error = search_url(config), [], [], None, None
    try:
        result = fetch_cards(config, headed=headed, pause=pause)
        cards, url, reason = result["cards"], result["url"], result["wait_reason"]
        rows = parse_cards(cards, config)
        if not rows:
            error = "讀到清單但未辨識出航班；原始卡片已保存，請檢查頁面與解析器"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    check_id, counts = record(database, config, started, url, cards, rows, reason, error)
    print(f"\n查詢 #{check_id} | {config['origin']} → {config['destination']} | {config['departure_date']}", flush=True)
    print(f"清單項目 {counts['raw']} | 航班 {counts['flights']} | 有報價 {counts['priced']} | "
          f"無報價 {counts['unavailable']} | 解析問題 {counts['problems']} | 符合篩選 {counts['matching']}", flush=True)
    if reason == "timeout":
        print("已達等待上限，保存目前讀到的資料；不保證結果完整。", flush=True)
    if error:
        print(f"查詢錯誤：{error}", file=sys.stderr, flush=True)
    print(f"已存入：{database}", flush=True)
    return 1 if error else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--database", type=Path, default=ROOT / "data/collection.sqlite3")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--pause", action="store_true", help="僅單次 headed 模式，核對後按 Enter")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-db", action="store_true", help="備份並重建 DB 後離開，不查價")
    args = parser.parse_args()
    
    import logging

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    from logging.handlers import TimedRotatingFileHandler

    handler = TimedRotatingFileHandler(
        log_dir / "monitor.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    ))

    logger = logging.getLogger("flight_monitor")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    class LogStream:
        def __init__(self, terminal, level):
            self.terminal = terminal
            self.level = level
            self.buffer = ""

        def write(self, text):
            self.terminal.write(text)
            self.buffer += text

            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                if line.strip():
                    logger.log(self.level, line)

            return len(text)

        def flush(self):
            self.terminal.flush()
            handler.flush()

    sys.stdout = LogStream(sys.stdout, logging.INFO)
    sys.stderr = LogStream(sys.stderr, logging.ERROR)

    logger.info("資料收集程式啟動")
    if args.pause and (not args.headed or args.watch):
        parser.error("--pause 只能搭配 --headed 單次查詢")
    if args.reset_db and (args.watch or args.dry_run):
        parser.error("--reset-db 請單獨執行")
    try:
        if args.reset_db:
            backup = reset_database(args.database)
            print(f"已重建：{args.database}")
            if backup:
                print(f"備份位置：{backup}")
            return 0
        config = load_config(args.config)
        if args.dry_run:
            print("設定驗證成功；未開啟瀏覽器、未寫入 DB。")
            for route in config["routes"]:
                route_config = {**config, **route}
                route_config.pop("routes", None)
                print(search_url(route_config))
            return 0
        connection = connect(args.database)
        connection.close()
        while True:
            status = 0

            for index, route in enumerate(config["routes"], start=1):
                route_config = {**config, **route}
                route_config.pop("routes", None)

                print(
                    f"\n本輪航線 {index}/{len(config['routes'])}",
                    flush=True,
                )

                status |= run_once(
                    route_config,
                    args.database,
                    args.headed,
                    args.pause,
                )
            if not args.watch:
                return status
            interval = config["interval_seconds"]
            print(f"等待 {interval} 秒；下一輪重新讀取 config。Ctrl+C 停止。", flush=True)
            time.sleep(interval)
            try:
                config = load_config(args.config)
            except (ValueError, KeyError, OSError, TypeError) as exc:
                # 設定無效時暫停查詢，定時重試讀取。
                print(f"設定錯誤，暫停查詢：{exc}", file=sys.stderr, flush=True)
                while True:
                    time.sleep(interval)
                    try:
                        config = load_config(args.config)
                        break
                    except (ValueError, KeyError, OSError, TypeError) as retry:
                        print(f"設定仍有錯誤：{retry}", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        print("\n已停止收集。")
        return 0
    except Exception as exc:
        print(f"執行失敗：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

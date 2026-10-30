"""將機票資料庫匯出成 GitHub Pages 使用的 JSON。"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from dashboard import read_data

ROOT = Path(__file__).resolve().parent
PUBLIC_FLIGHT_FIELDS = (
    'id', 'check_id', 'checked_at', 'origin', 'destination', 'departure_date',
    'return_date', 'currency', 'price', 'price_status', 'airline',
    'departure_time', 'arrival_time', 'arrival_day_offset', 'duration_minutes',
    'stops', 'key', 'change', 'previous_time', 'history_min', 'history_max',
    'observations', 'raw_text',
)


def public_check(check):
    if check is None:
        return None
    config = json.loads(check['config_json'])
    return {
        'id': check['id'],
        'checked_at': check['checked_at'],
        'status': check['status'],
        'error': '查詢失敗' if check.get('error') else None,
        'config_json': json.dumps({'interval_seconds': config.get('interval_seconds', 3600)}),
    }


def public_view(view):
    result = {
        'latest_attempt': public_check(view['latest_attempt']),
        'latest_data': public_check(view['latest_data']),
        'flights': [{key: row.get(key) for key in PUBLIC_FLIGHT_FIELDS} for row in view['flights']],
        'history': view['history'],
        'series': view['series'],
        'checks': [public_check(check) for check in view['checks']],
        'excluded': view.get('excluded', 0),
        'totals': view.get('totals', {'checks': len(view['checks']), 'observations': 0}),
        'previous_time': view.get('previous_time'),
    }
    return result


def write_json(path, value):
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.export-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            file.write(payload)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def export(database, output):
    database = Path(database).resolve()
    output = Path(output).resolve()
    if not database.is_file():
        raise ValueError(f'找不到資料庫：{database}')
    timestamp = datetime.now(timezone.utc).isoformat()
    # 同一批匯出使用一致的 DB 快照，不修改收集中的來源 DB。
    with tempfile.TemporaryDirectory() as temp:
        snapshot = Path(temp) / 'snapshot.sqlite3'
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
                target.commit()
        initial = read_data(snapshot)
        routes = initial['routes']
        files = []
        for index in range(len(routes)):
            views = {}
            for nonstop in (0, 1):
                for duration in (None, 240, 360):
                    for hours in (0, 24, 168):
                        key = f'{nonstop}|{duration or "all"}|{hours}'
                        view = read_data(snapshot, index, bool(nonstop), duration, hours)
                        views[key] = public_view(view)
            name = f'route-{index}.json'
            write_json(output / name, {'exported_at': timestamp, 'views': views})
            files.append(name)
        write_json(output / 'meta.json', {
            'exported_at': timestamp,
            'routes': routes,
            'files': files,
        })
    return len(routes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/collection.sqlite3')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/data')
    args = parser.parse_args()
    try:
        count = export(args.database, args.output)
    except Exception as error:
        parser.exit(1, f'匯出失敗：{error}\n')
    print(f'已匯出 {count} 組航線：{args.output.resolve()}')
    print('推送 docs 到 GitHub 後，網站才會更新。')


if __name__ == '__main__':
    main()

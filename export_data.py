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
from config import load_config

ROOT = Path(__file__).resolve().parent
PUBLIC_FLIGHT_FIELDS = (
    'price',
    'airline',
    'departure_time',
    'arrival_time',
    'arrival_day_offset',
    'duration_minutes',
    'stops',
    'key',
    'history_min',
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


def sync_frontend(site_root):
    source = ROOT / 'frontend'
    names = ('dashboard.html', 'dashboard.js', 'dashboard.css')
    contents = {name: (source / name).read_bytes() for name in names}
    html = contents['dashboard.html'].decode('utf-8')
    marker = 'data-source="api"'
    if marker not in html:
        raise ValueError('共用 HTML 缺少 API 模式標記')
    site_root.mkdir(parents=True, exist_ok=True)
    assets = site_root / 'frontend'
    assets.mkdir(parents=True, exist_ok=True)
    (site_root / 'index.html').write_text(
        html.replace(marker, 'data-source="json"', 1), encoding='utf-8')
    for name in ('dashboard.js', 'dashboard.css'):
        (assets / name).write_bytes(contents[name])
    (site_root / '.nojekyll').touch()


def export(database, output, config_path):
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
        config = load_config(config_path)
        configured_routes = config['routes']

        initial = read_data(snapshot)
        database_routes = initial['routes']

        routes = []
        route_indices = []

        for route in configured_routes:
            match = next(
                (
                    index
                    for index, db_route in enumerate(database_routes)
                    if all(
                        db_route.get(field) == route.get(field)
                        for field in (
                            'origin',
                            'destination',
                            'departure_date',
                            'return_date',
                        )
                    )
                ),
                None,
            )

            if match is None:
                raise ValueError(
                    f"資料庫找不到設定中的航線："
                    f"{route['origin']} → {route['destination']} "
                    f"{route['departure_date']}"
                )

            routes.append(database_routes[match])
            route_indices.append(match)
        files = []
        for output_index, database_index in enumerate(route_indices):
            view = read_data(
                snapshot,
                route_index=database_index,
                nonstop=False,
                max_duration=None,
                hours=0,
            )
            name = f'route-{output_index}.json'

            write_json(
                output / name,
                {
                    'exported_at': timestamp,
                    'data': public_view(view),
                },
            )

            files.append(name)
        write_json(output / 'meta.json', {
            'exported_at': timestamp,
            'routes': routes,
            'files': files,
        })
        # 清除本次匯出未使用的舊航線 JSON
        for old_file in output.glob('route-*.json'):
            if old_file.name not in files:
                old_file.unlink()
    sync_frontend(output.parent)
    return len(routes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/collection.sqlite3')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/data')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    args = parser.parse_args()
    try:
        count = export(args.database, args.output, args.config)
    except Exception as error:
        parser.exit(1, f'匯出失敗：{error}\n')
    print(f'已匯出 {count} 組航線：{args.output.resolve()}')
    print('推送 docs 到 GitHub 後，網站才會更新。')


if __name__ == '__main__':
    main()

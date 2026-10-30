"""機票追蹤儀表板，唯讀存取 SQLite。"""
from contextlib import closing
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
ROUTE = ('origin','destination','departure_date','return_date','currency')


def route_key(row):
    return tuple(row.get(k) for k in ROUTE)


def flight_key(row):
    return json.dumps([row.get(k) for k in ('airline','departure_time','arrival_time',
                      'arrival_day_offset','duration_minutes','stops')],ensure_ascii=False)


def valid(row):
    name = row.get('airline') or ''
    return (0 < len(name) <= 80 and not re.search(r'\d|on Thu|Departure|layover|Airport',name,re.I)
            and all(re.fullmatch(r'\d{2}:\d{2}', row.get(k) or '') for k in ('departure_time','arrival_time'))
            and isinstance(row.get('stops'),int) and 0 <= row['stops'] <= 5
            and isinstance(row.get('duration_minutes'),int) and 0 < row['duration_minutes'] <= 4320
            and row.get('parse_status') == 'ok')


def read_data(database, route_index=None, nonstop=True, max_duration=None, hours=24):
    with closing(sqlite3.connect(
        Path(database).resolve().as_uri() + '?mode=ro',
        uri=True,
        timeout=10,
    )) as c:
        c.row_factory=sqlite3.Row
        c.execute("BEGIN")
        checks=[dict(r) for r in c.execute('SELECT id,checked_at,finished_at,status,config_json,error FROM checks ORDER BY id')]
        routes=[]
        for check in checks:
            try:
                config=json.loads(check['config_json'])
            except (ValueError,TypeError):
                continue
            check['route']=route_key(config)
            if check['route'] not in routes:
                routes.append(check['route'])
        if not routes:
            return {'routes':[], 'flights':[], 'history':[], 'series':[], 'checks':[]}
        if route_index is None:
            route_index=len(routes)-1
        if not 0 <= route_index < len(routes):
            raise ValueError('找不到航線')
        route=routes[route_index]
        selected=[x for x in checks if x.get('route')==route]
        latest_attempt=selected[-1]
        # 只保留所選航線，DB 以參數查詢。
        rows=[dict(r) for r in c.execute('''SELECT * FROM flight_prices WHERE origin=? AND destination=?
              AND departure_date=? AND return_date IS ? AND currency=? ORDER BY check_id,id''',route)]
    with_rows={r['check_id'] for r in rows}
    latest_data=next((x for x in reversed(selected) if x['id'] in with_rows),None)
    if not latest_data:
        return {'routes':[dict(zip(ROUTE,r)) for r in routes], 'route_index':route_index,
                'latest_attempt':latest_attempt,'latest_data':None,'flights':[], 'history':[], 'series':[], 'checks':selected[-30:]}
    end=datetime.fromisoformat(latest_attempt['checked_at'])
    cutoff=end-timedelta(hours=hours) if hours else datetime.min.replace(tzinfo=end.tzinfo)
    chosen_checks=[x for x in selected if datetime.fromisoformat(x['checked_at'])>=cutoff]
    ids={x['id'] for x in chosen_checks}
    def matches(row):
        return valid(row) and (not nonstop or row['stops']==0) and (max_duration is None or row['duration_minutes']<=max_duration)
    accepted=[r for r in rows if matches(r)]
    groups=defaultdict(dict)
    for row in accepted:
        key=flight_key(row)
        # 同輪相同身份只留一筆，優先保留有報價者。
        existing=groups[row['check_id']].get(key)
        if existing is None or (existing['price'] is None and row['price'] is not None):
            groups[row['check_id']][key]=row
    latest_id=latest_data['id']
    previous=next((x for x in reversed(selected) if x['id']<latest_id),None)
    prev=groups.get(previous['id'],{}) if previous else {}
    history=[]
    by_flight=defaultdict(list)
    for check in chosen_checks:
        offers=list(groups.get(check['id'],{}).values())
        priced=[r['price'] for r in offers if r['price'] is not None and r['price']>0]
        history.append({'check_id':check['id'],'time':check['checked_at'],
                        'price':min(priced) if priced else None,'count':len(priced),'status':check['status']})
    for row in accepted:
        if row['check_id'] in ids:
            by_flight[flight_key(row)].append(row)
    flights=[]
    for key,row in groups.get(latest_id,{}).items():
        p=prev.get(key)
        values=[x['price'] for x in by_flight[key] if x['price'] is not None and x['price']>0]
        flights.append({**row,'key':key,
            'change':row['price']-p['price'] if p and p['price'] is not None and row['price'] is not None else None,
            'previous_time':previous['checked_at'] if previous else None,
            'history_min':min(values) if values else None,
            'history_max':max(values) if values else None,
            'observations':len(by_flight[key])})
    flights.sort(key=lambda x:(x['price'] is None,x['price'] or 0,x['departure_time']))
    series=[]
    for key,observations in by_flight.items():
        lookup={r['check_id']:r for r in observations}
        row=observations[-1]
        series.append({'key':key,'label':f"{row['airline']} · {row['departure_time']} → {row['arrival_time']}",
                       'points':[{'time':x['checked_at'],'price':lookup[x['id']]['price'] if x['id'] in lookup else None}
                                 for x in chosen_checks]})
    latest_rows=[r for r in rows if r['check_id']==latest_id]
    return {'routes':[dict(zip(ROUTE,r)) for r in routes], 'route_index':route_index,
            'latest_attempt':latest_attempt,'latest_data':latest_data,'flights':flights,
            'history':history,'series':series,'checks':list(reversed(chosen_checks[-30:])),
            'excluded':sum(not valid(r) for r in latest_rows),
            'totals':{'checks':len(chosen_checks),'observations':sum(len(v) for v in by_flight.values())},
            'previous_time':previous['checked_at'] if previous else None}


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlparse(self.path)
            try:
                if path.path=='/api/data':
                    q=parse_qs(path.query)
                    index=int(q['route'][0]) if 'route' in q else None
                    nonstop=q.get('nonstop',['1'])[0]=='1'
                    maximum=int(q['duration'][0]) if q.get('duration',[''])[0] else None
                    hours=int(q.get('hours',['24'])[0])
                    if hours not in (0,24,168) or (maximum is not None and maximum<=0):
                        raise ValueError('篩選條件不正確')
                    payload=json.dumps(read_data(database,index,nonstop,maximum,hours),ensure_ascii=False,allow_nan=False).encode()
                    content_type='application/json; charset=utf-8'
                elif path.path in (
                    "/",
                    "/frontend/dashboard.css",
                    "/frontend/dashboard.js",
                ):
                    files = {
                        "/": (
                            "dashboard.html",
                            "text/html; charset=utf-8",
                        ),
                        "/frontend/dashboard.css": (
                            "dashboard.css",
                            "text/css; charset=utf-8",
                        ),
                        "/frontend/dashboard.js": (
                            "dashboard.js",
                            "text/javascript; charset=utf-8",
                        ),
                    }

                    filename, content_type = files[path.path]
                    payload = (ROOT / "frontend" / filename).read_bytes()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type',content_type)
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                payload=json.dumps({'error':str(exc)},ensure_ascii=False).encode()
                self.send_response(400)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(payload)
        def log_message(self,*args):
            pass
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'data/collection.sqlite3')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if not args.database.is_file():
        parser.error(f'找不到資料庫：{args.database}')
    server = ThreadingHTTPServer(
        ("0.0.0.0", args.port),
        make_handler(args.database),
    )
    print(f'機票 Monitor：http://127.0.0.1:{args.port}\n資料庫：{args.database.resolve()}\nCtrl+C 停止',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()

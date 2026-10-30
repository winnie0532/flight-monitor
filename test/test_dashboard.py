import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from dashboard import read_data,make_handler

class DashboardTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.db=Path(self.tmp.name)/'test.sqlite3'
  self.cfg=dict(origin='TPE',destination='NRT',departure_date='2026-12-10',return_date=None,currency='TWD')
  with sqlite3.connect(self.db) as c:
   c.executescript('''CREATE TABLE checks(id INTEGER PRIMARY KEY,checked_at TEXT,finished_at TEXT,status TEXT,config_json TEXT,error TEXT);
   CREATE TABLE flight_prices(id INTEGER PRIMARY KEY,check_id INTEGER,checked_at TEXT,origin TEXT,destination TEXT,departure_date TEXT,return_date TEXT,currency TEXT,price NUMERIC,airline TEXT,departure_time TEXT,arrival_time TEXT,arrival_day_offset INTEGER,duration_minutes INTEGER,stops INTEGER,parse_status TEXT,raw_text TEXT);''')
   for i,p in ((1,5000),(2,4800),(3,None)):
    t=f'2026-10-30T0{i}:00:00+00:00';c.execute('INSERT INTO checks VALUES(?,?,?,?,?,?)',(i,t,t,'ok',json.dumps(self.cfg),None))
    c.execute('INSERT INTO flight_prices VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(i,i,t,'TPE','NRT','2026-12-10',None,'TWD',p,'Scoot','06:50','10:55',0,185,0,'ok','fixture'))
 def test_missing_quote_is_gap(self):
  d=read_data(self.db);self.assertEqual([x['price'] for x in d['history']],[5000,4800,None]);self.assertIsNone(d['flights'][0]['change']);self.assertEqual(d['flights'][0]['history_min'],4800)
 def test_change_same_flight(self):
  with sqlite3.connect(self.db) as c:c.execute('DELETE FROM checks WHERE id=3');c.execute('DELETE FROM flight_prices WHERE check_id=3')
  self.assertEqual(read_data(self.db)['flights'][0]['change'],-200)
 def test_suspect_excluded(self):
  with sqlite3.connect(self.db) as c:c.execute("UPDATE flight_prices SET airline='on Thu, Dec 10 6:15 PM',stops=9801 WHERE check_id=3")
  d=read_data(self.db);self.assertEqual(d['excluded'],1);self.assertEqual(d['flights'],[])
 def test_filter_applies_to_history(self):
  with sqlite3.connect(self.db) as c:c.execute('UPDATE flight_prices SET stops=1')
  self.assertEqual(read_data(self.db,nonstop=True)['flights'],[]);self.assertEqual(len(read_data(self.db,nonstop=False)['flights']),1)
 def test_failed_attempt_explicit(self):
  with sqlite3.connect(self.db) as c:c.execute('INSERT INTO checks VALUES(?,?,?,?,?,?)',(4,'2026-10-30T04:00:00+00:00','2026-10-30T04:00:00+00:00','error',json.dumps(self.cfg),'timeout'))
  d=read_data(self.db);self.assertEqual(d['latest_attempt']['id'],4);self.assertEqual(d['latest_data']['id'],3);self.assertIsNone(d['history'][-1]['price'])
 def test_route_isolation(self):
  cfg=dict(self.cfg,origin='SIN',destination='DPS')
  with sqlite3.connect(self.db) as c:c.execute('INSERT INTO checks VALUES(?,?,?,?,?,?)',(4,'2026-10-30T04:00:00+00:00','2026-10-30T04:00:00+00:00','error',json.dumps(cfg),'offline'))
  d=read_data(self.db,route_index=1);self.assertIsNone(d['latest_data']);self.assertEqual(d['flights'],[])
 def test_read_only(self):
  before=hashlib.sha256(self.db.read_bytes()).digest();read_data(self.db);self.assertEqual(hashlib.sha256(self.db.read_bytes()).digest(),before)
 def test_http(self):
  server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.db));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base=f'http://127.0.0.1:{server.server_port}'
   with urlopen(base+'/api/data?duration=240&hours=24') as r:self.assertEqual(len(json.load(r)['flights']),1)
   with urlopen(base+'/') as r:self.assertIn('Flight Monitor',r.read().decode())
   with self.assertRaises(HTTPError):urlopen(base+'/api/data?hours=-1')
  finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()

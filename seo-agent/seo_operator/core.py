from __future__ import annotations
import contextlib, datetime as dt, hashlib, json, os, sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def normalize_url(url):
    p = urlsplit(url)
    # Paths and query values can be case-sensitive. Preserve both.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', p.query, ''))

def config(path=None):
    default=ROOT/'config.json'
    p = Path(path or (default if default.exists() else ROOT/'config.example.json')).resolve()
    c = json.loads(p.read_text()); c['_root'] = str(p.parent)
    c['_runtime'] = str(p.parent / c.get('runtime', 'runtime'))
    return c

def secrets():
    return {key:os.environ[key] for key in ('GOOGLE_OAUTH_TOKEN_FILE','GOOGLE_APPLICATION_CREDENTIALS','PAYLOAD_API_KEY') if key in os.environ}

def final_date():
    return dt.datetime.now(ZoneInfo('America/Los_Angeles')).date() - dt.timedelta(days=3)

def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n'); tmp.replace(path)

class Store:
    def __init__(self, path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, kind TEXT, started TEXT, finished TEXT, status TEXT, details TEXT);
        CREATE TABLE IF NOT EXISTS coverage(site TEXT, kind TEXT, day TEXT, status TEXT, note TEXT, checked TEXT, PRIMARY KEY(site,kind,day));
        CREATE TABLE IF NOT EXISTS search_rows(site TEXT, day TEXT, query TEXT, page TEXT, country TEXT, device TEXT, clicks REAL, impressions REAL, position REAL, PRIMARY KEY(site,day,query,page,country,device));
        CREATE TABLE IF NOT EXISTS analytics(site TEXT, day TEXT, page TEXT, sessions REAL, conversions REAL, PRIMARY KEY(site,day,page));
        CREATE TABLE IF NOT EXISTS pages(site TEXT, url TEXT, checked TEXT, document TEXT, PRIMARY KEY(site,url));
        CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY, site TEXT, page TEXT, query TEXT, kind TEXT, score REAL, evidence TEXT, status TEXT DEFAULT 'open', created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS content(id TEXT PRIMARY KEY, site TEXT, slug TEXT, revision TEXT, state TEXT, document TEXT, remote_id TEXT, previous TEXT, updated TEXT, UNIQUE(site,slug));
        CREATE TABLE IF NOT EXISTS publications(id INTEGER PRIMARY KEY, content_id TEXT, revision TEXT, site TEXT, kind TEXT, published TEXT, UNIQUE(content_id,revision));
        CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY, content_id TEXT, created TEXT, document TEXT);
        CREATE TABLE IF NOT EXISTS prospects(id TEXT PRIMARY KEY, site TEXT, source_url TEXT, target_url TEXT, rationale TEXT, draft TEXT, status TEXT, observed TEXT, checked TEXT);
        ''')
    def rows(self, sql, params=()):
        return [dict(r) for r in self.db.execute(sql, params)]
    def execute(self, sql, params=()):
        with self.db: return self.db.execute(sql, params)
    def coverage(self, site, kind, day, status, note=''):
        self.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?,?,?,?)', (site,kind,day,status,note,now()))
    @contextlib.contextmanager
    def run(self, kind):
        rid = self.execute('INSERT INTO runs(kind,started,status) VALUES(?,?,?)',(kind,now(),'running')).lastrowid
        try:
            yield rid
        except Exception as exc:
            self.execute('UPDATE runs SET finished=?,status=?,details=? WHERE id=?',(now(),'failed',type(exc).__name__,rid));raise
        else: self.execute('UPDATE runs SET finished=?,status=? WHERE id=?',(now(),'complete',rid))

@contextlib.contextmanager
def lock(c):
    import fcntl
    p = Path(c['_runtime']); p.mkdir(parents=True,exist_ok=True)
    with (p/'operation.lock').open('w') as f:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another SEO operation is running')
        try: yield
        finally: fcntl.flock(f,fcntl.LOCK_UN)

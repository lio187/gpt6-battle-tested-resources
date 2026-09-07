"""Local CRM pilot. An event ledger is authoritative for applications, not contacts.

Comp AI's API is an eventually consistent projection. No production CRM writes,
mail sending, automatic enrichment or third-party credentials are used here.
"""
from __future__ import annotations
import argparse, contextlib, datetime as dt, hashlib, hmac, json, os, re
import sqlite3, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

DEFAULT_SITE_HOSTS = {'primary': 'example.com', 'academy': 'example.org'}
KINDS = {'application', 'qualified', 'disqualified', 'won', 'lost', 'payment', 'refund'}
DEFAULT = Path(__file__).resolve().parents[1] / 'crm-config.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def canonical_event(value, site_hosts=None):
    site_hosts = site_hosts or DEFAULT_SITE_HOSTS
    if not isinstance(value, dict):
        raise ValueError('Event must be an object')
    allowed = {'event_id', 'site', 'source', 'application_id', 'kind', 'occurred_at',
               'contact', 'company', 'attribution', 'amount_cents', 'transaction_id'}
    if set(value) - allowed:
        raise ValueError('Unknown event fields')
    e = json.loads(json.dumps(value))
    for key in ('event_id', 'source', 'application_id'):
        if not isinstance(e.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,150}', e[key]):
            raise ValueError('Invalid ' + key)
    if not isinstance(e.get('site'), str) or not isinstance(e.get('kind'), str) or e['site'] not in site_hosts or e['kind'] not in KINDS:
        raise ValueError('Invalid site or kind')
    try:
        stamp = dt.datetime.fromisoformat(e['occurred_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError()
        e['occurred_at'] = stamp.astimezone(dt.timezone.utc).isoformat()
    except (KeyError, ValueError, AttributeError):
        raise ValueError('occurred_at needs an ISO timestamp with timezone')
    if stamp.timestamp() > time.time() + 300:
        raise ValueError('Event timestamp is in the future')
    contact = e.get('contact', {})
    if not isinstance(contact, dict) or set(contact) - {'email', 'first_name', 'last_name'}:
        raise ValueError('Invalid contact')
    if not isinstance(contact.get('email'), str):
        raise ValueError('A contact email is required')
    email = contact['email'].strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email) > 254:
        raise ValueError('A valid contact email is required')
    if not isinstance(contact.get('first_name'), str) or not contact['first_name'].strip():
        raise ValueError('first_name is required; do not infer names from email addresses')
    for key in ('first_name', 'last_name'):
        if key in contact and (not isinstance(contact[key], str) or len(contact[key]) > 200):
            raise ValueError('Invalid contact name')
    e['contact'] = {**contact, 'email': email}
    company = e.get('company')
    if company is not None:
        if not isinstance(company, dict) or set(company) != {'name', 'domain'}:
            raise ValueError('Company requires only name and domain')
        if not isinstance(company['name'], str) or not 1 <= len(company['name']) <= 200:
            raise ValueError('Invalid company name')
        if not isinstance(company['domain'], str):
            raise ValueError('Company domain must be text')
        domain = company['domain'].lower().strip()
        if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', domain):
            raise ValueError('Company domain must be an observed hostname')
        company['domain'] = domain
    attribution = e.get('attribution', {})
    if not isinstance(attribution, dict) or set(attribution) - {'landing_page', 'channel', 'campaign'}:
        raise ValueError('Invalid attribution')
    for key, val in attribution.items():
        if not isinstance(val, str) or len(val) > 2000:
            raise ValueError('Invalid attribution value')
    url = attribution.get('landing_page')
    if url:
        p = urllib.parse.urlsplit(url)
        host=site_hosts[e['site']]
        if p.scheme != 'https' or p.hostname not in (host, 'www.' + host) or p.username or p.password or p.port not in (None,443):
            raise ValueError('Landing page must belong to the event site')
        attribution['landing_page'] = urllib.parse.urlunsplit(('https', p.hostname, p.path or '/', '', ''))
    e['attribution'] = attribution
    money = e['kind'] in ('payment', 'refund')
    if money:
        if type(e.get('amount_cents')) is not int or not 0 < e['amount_cents'] <= 100_000_000_000:
            raise ValueError('Positive integer EUR cents required')
        if not isinstance(e.get('transaction_id'), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,150}', e['transaction_id']):
            raise ValueError('Stable payment/refund transaction_id required')
    elif 'amount_cents' in e or 'transaction_id' in e:
        raise ValueError('Only payment/refund events record realized revenue')
    return e


class Ledger:
    def __init__(self, path, site_hosts=None):
        self.path = Path(path)
        self.site_hosts = site_hosts or DEFAULT_SITE_HOSTS
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        os.chmod(self.path, 0o600)
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS events(
          key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, site TEXT NOT NULL,
          source TEXT NOT NULL, application_id TEXT NOT NULL, kind TEXT NOT NULL,
          occurred_at TEXT NOT NULL, document TEXT NOT NULL,
          UNIQUE(site,source,kind,application_id,fingerprint));
        CREATE TABLE IF NOT EXISTS payments(
          site TEXT, source TEXT, transaction_id TEXT, fingerprint TEXT,
          PRIMARY KEY(site,source,transaction_id));
        CREATE TABLE IF NOT EXISTS jobs(
          application_key TEXT PRIMARY KEY, revision INTEGER DEFAULT 1,
          status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
          next_attempt REAL DEFAULT 0, error TEXT, remote_contact TEXT, remote_deal TEXT);
        CREATE TABLE IF NOT EXISTS mappings(kind TEXT, local_id TEXT, remote_id TEXT,
          PRIMARY KEY(kind,local_id));
        CREATE TABLE IF NOT EXISTS link_prospects(id TEXT PRIMARY KEY, document TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def ingest(self, value):
        e = canonical_event(value,self.site_hosts)
        key = digest([e['site'], e['source'], e['event_id']])
        fp = digest(e)
        app_key = digest([e['site'], e['source'], e['application_id']])
        with self.db:
            # Serialize deduplication and projection invalidation across HTTP/worker processes.
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT fingerprint FROM events WHERE key=?', (key,)).fetchone()
            if old:
                if old[0] != fp:
                    raise ValueError('Event ID reused with different data')
                return {'status': 'duplicate', 'event_key': key}
            previous = self.db.execute('SELECT document FROM events WHERE site=? AND source=? AND application_id=?',
                                       (e['site'], e['source'], e['application_id'])).fetchall()
            for row in previous:
                if json.loads(row[0])['contact']['email'] != e['contact']['email']:
                    raise ValueError('Application contact cannot change')
            if e['kind'] in ('payment', 'refund'):
                # Event IDs may differ across webhook redelivery; transaction is authoritative.
                payment_fp = digest({k: v for k, v in e.items() if k != 'event_id'})
                old = self.db.execute('SELECT fingerprint FROM payments WHERE site=? AND source=? AND transaction_id=?',
                                      (e['site'], e['source'], e['transaction_id'])).fetchone()
                if old:
                    if old[0] != payment_fp:
                        raise ValueError('Transaction ID reused with different data')
                    return {'status': 'duplicate-transaction', 'event_key': key}
                self.db.execute('INSERT INTO payments VALUES(?,?,?,?)', (e['site'],e['source'],e['transaction_id'],payment_fp))
            self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)',
                            (key,fp,e['site'],e['source'],e['application_id'],e['kind'],e['occurred_at'],json.dumps(e)))
            self.db.execute('''INSERT INTO jobs(application_key) VALUES(?) ON CONFLICT(application_key)
              DO UPDATE SET revision=revision+1,status='pending',next_attempt=0,error=NULL''', (app_key,))
        return {'status': 'accepted', 'event_key': key, 'application_key': app_key}

    def applications(self):
        groups = {}
        for row in self.db.execute('SELECT * FROM events ORDER BY occurred_at,key'):
            e = json.loads(row['document'])
            key = digest([e['site'],e['source'],e['application_id']])
            groups.setdefault(key, []).append(e)
        result = []
        for key, events in groups.items():
            applications = [e for e in events if e['kind'] == 'application']
            if not applications:  # Out-of-order delivery is retained but not misreported as a lead.
                continue
            first = applications[0]
            states = [e for e in events if e['kind'] in {'application','qualified','disqualified','won','lost'}]
            latest = states[-1]
            result.append({**first, 'key':key, 'state':latest['kind'], 'updated_at':latest['occurred_at'],
                           'qualified':any(e['kind']=='qualified' for e in events),
                           'revenue_cents':sum(e.get('amount_cents',0) * (-1 if e['kind']=='refund' else 1)
                                               for e in events if e['kind'] in ('payment','refund'))})
        return result

    def summary(self):
        groups = {}
        for a in self.applications():
            at = a['attribution']
            key = (a['site'], at.get('landing_page') or 'unknown', at.get('channel') or 'unknown',at.get('campaign') or 'unknown', a['source'])
            r = groups.setdefault(key, dict(zip(('site','landing_page','channel','campaign','source'),key)) | {
                'applications':0,'qualified_ever':0,'won':0,'revenue_cents':0,'currency':'EUR'})
            r['applications'] += 1
            r['qualified_ever'] += int(a['qualified'])
            r['won'] += int(a['state']=='won')
            r['revenue_cents'] += a['revenue_cents']
        jobs = {r[0]:r[1] for r in self.db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status')}
        from .crm_imports import sales_mapping
        return {'mode':'local-pilot', 'attribution':'first application; observed channel only; no query attribution',
                'rows':list(groups.values()), 'jobs':jobs,
                'events':self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                'applications':len(self.applications()),
                'sales_mapping':sales_mapping(self),
                'link_prospects':[json.loads(r[0]) for r in self.db.execute('SELECT document FROM link_prospects')]}

    def mapping(self, kind, local, remote=None):
        if remote:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?,?)',(kind,local,remote))
        row = self.db.execute('SELECT remote_id FROM mappings WHERE kind=? AND local_id=?',(kind,local)).fetchone()
        return row[0] if row else None

    def backup(self, target):
        target = Path(target)
        if target.exists():
            raise ValueError('Backup destination must not exist')
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as dest:
            self.db.backup(dest)
        os.chmod(target, 0o600)
        return {'backup':str(target)}


class ApiError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__('CRM HTTP ' + str(status))


class CompAI:
    def __init__(self, url, key):
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'http' or p.hostname != '127.0.0.1' or p.path not in ('','/') or p.query or p.fragment or p.username:
            raise ValueError('Pilot CRM API must be http://127.0.0.1:PORT')
        if not key:
            raise ValueError('CRM API key is not configured')
        self.url, self.key = url.rstrip('/'), key
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, method, path, data=None):
        req = urllib.request.Request(self.url+'/rest'+path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'x-api-key':self.key,'Content-Type':'application/json'},method=method)
        try:
            with self.opener.open(req, timeout=20) as res:
                raw = res.read(2_000_001)
                if len(raw)>2_000_000:
                    raise RuntimeError('CRM response too large')
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code) from None
        except (urllib.error.URLError, TimeoutError):
            raise ApiError(503) from None

    def search(self, entity, q):
        rows, page = [], 1
        while page <= 100:
            res = self.call('POST',f'/{entity}/search',{'q':q,'page':page,'pageSize':100})
            rows.extend(res['rows'])
            if len(rows) >= res['total']:
                return rows
            if not res['rows']:
                raise RuntimeError('Incomplete CRM pagination')
            page += 1
        raise RuntimeError('CRM search exceeded pilot limit')

    def fields(self, entity, labels):
        existing = self.call('GET','/fields?entity='+entity)
        found = {}
        for label in labels:
            matches = [f for f in existing if f['label']==label and not f['archived']]
            if len(matches)>1:
                raise RuntimeError('Ambiguous CRM field')
            f = matches[0] if matches else self.call('POST','/fields',{
                'entity':entity,'label':label,'type':'TEXT','agentFilled':False,
                'showOnSheet':True,'showOnTable':True,'showOnFilter':True})
            if f['type']!='TEXT' or f['agentFilled']:
                raise RuntimeError('Pilot fields must be text and not agent-filled')
            found[label] = f['key']
        return found

    def ensure(self, store, entity, local, match, create):
        known = store.mapping(entity, local)
        if known:
            self.call('GET',f'/{entity}/{urllib.parse.quote(known,safe="")}')
            return known
        rows = self.search(entity, local)
        matches = [r for r in rows if match(r)]
        if len(matches)>1:
            raise RuntimeError('Ambiguous CRM identity; manual reconciliation required')
        if matches:
            remote = matches[0]['id']
        else:
            try:
                remote = self.call('POST','/'+entity,create)['id']
            except ApiError as exc:
                if exc.status != 409:
                    raise
                matches = [r for r in self.search(entity,local) if match(r)]
                if len(matches)!=1:
                    raise
                remote = matches[0]['id']
        store.mapping(entity,local,remote)
        return remote

    def project(self, store, application, owner_id):
        a = application
        c = a['contact']; email = c['email']
        contact = self.ensure(store,'contacts',email,lambda r:(r.get('email') or '').lower()==email,
            {'firstName':c['first_name'],'lastName':c.get('last_name',''),'email':email})
        # Per-brand summaries preserve cross-brand membership; ledger retains all applications.
        all_apps = [r for r in store.applications() if r['contact']['email']==email and r['site']==a['site']]
        newest = max(all_apps,key=lambda r:(r['occurred_at'],r['key']))
        prefix = 'SEO '+a['site']+' '
        values = {'Applications':str(len(all_apps)), 'Status':newest['state'],
                  'Application ID':newest['application_id'], 'Application key':newest['key'], 'Source':newest['source'],
                  'Landing page':newest['attribution'].get('landing_page','unknown'),
                  'Channel':newest['attribution'].get('channel','unknown'),
                  'Campaign':newest['attribution'].get('campaign','unknown'),
                  'Revenue EUR cents':str(sum(r['revenue_cents'] for r in all_apps))}
        fields = self.fields('CONTACT',[prefix+k for k in values])
        self.call('PATCH','/contacts/'+contact,{'data':{'fields':{fields[prefix+k]:v for k,v in values.items()}}})
        deal = None
        stage = {'qualified':'QUALIFIED_TO_BUY','disqualified':'UNQUALIFIED_TO_BUY','won':'CLOSED_WON','lost':'CLOSED_LOST'}.get(a['state'])
        if a.get('company') and stage:
            if not owner_id:
                raise ValueError('Local Comp AI deal owner ID required')
            co = a['company']; domain = co['domain']
            company = self.ensure(store,'companies',domain,lambda r:r.get('domain')==domain,
                                  {'name':co['name'],'domain':domain})
            name = 'SEO '+a['site']+' '+a['key']  # Stable searchable identity, including crash-after-create recovery.
            deal = self.ensure(store,'deals',name,lambda r:r['name']==name,
                               {'name':name,'companyId':company,'ownerId':owner_id,'currency':'EUR','stage':stage})
            stage_data = {'stage':stage}
            if stage in {'UNQUALIFIED_TO_BUY','CLOSED_LOST'}:
                stage_data['closedReason'] = 'Local pilot application status: '+a['state']
            self.call('PATCH','/deals/'+deal+'/stage',stage_data)
            df = self.fields('DEAL',['SEO Application ID','SEO Status','SEO Landing page','SEO Source'])
            vals = {'SEO Application ID':a['application_id'],'SEO Status':a['state'],
                    'SEO Landing page':a['attribution'].get('landing_page','unknown'),'SEO Source':a['source']}
            self.call('PATCH','/deals/'+deal,{'data':{'fields':{df[k]:v for k,v in vals.items()}}})
        return contact, deal


@contextlib.contextmanager
def worker_lock(path):
    import fcntl
    with Path(path).open('a') as f:
        try:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another CRM worker is running')
        try:
            yield
        finally:
            fcntl.flock(f,fcntl.LOCK_UN)


def sync(store, api, owner_id, limit=25):
    result = {'synced':0,'failed':0,'waiting_application':0}
    with worker_lock(str(store.path)+'.worker.lock'):
        # Take applications and queue revisions from the same SQLite read snapshot.
        with store.db:
            store.db.execute('BEGIN')
            apps = {a['key']:a for a in store.applications()}
            jobs = list(store.db.execute("SELECT * FROM jobs WHERE status!='synced' AND next_attempt<=? ORDER BY next_attempt LIMIT ?",(time.time(),limit)))
        for j in jobs:
            a = apps.get(j['application_key'])
            if a is None:
                result['waiting_application'] += 1
                continue
            try:
                contact, deal = api.project(store,a,owner_id)
                with store.db:
                    store.db.execute("UPDATE jobs SET status='synced',error=NULL,remote_contact=?,remote_deal=? WHERE application_key=? AND revision=?",
                                     (contact,deal,j['application_key'],j['revision']))
                result['synced'] += 1
            except (ApiError,ValueError,RuntimeError,KeyError,TypeError) as exc:
                # Store classes/status only. Never response bodies, keys, or event payloads.
                delay = min(3600,30*2**min(j['attempts'],7))
                error = str(exc) if isinstance(exc,ApiError) else type(exc).__name__
                with store.db:
                    store.db.execute("UPDATE jobs SET status='retry',attempts=attempts+1,next_attempt=?,error=? WHERE application_key=? AND revision=?",
                                     (time.time()+delay,error,j['application_key'],j['revision']))
                result['failed'] += 1
    return result



def pull(store, api):
    """Read human CRM stage edits back as observed events; never infer payments.

    Pending intake has precedence. Only the latest course application is represented
    by the per-brand contact status; earlier applications remain in the ledger.
    """
    result = {'observed_changes':0, 'failed':0}
    with worker_lock(str(store.path)+'.worker.lock'):
        apps = {a['key']:a for a in store.applications()}
        for job in list(store.db.execute("SELECT * FROM jobs WHERE status='synced'")):
            a = apps.get(job['application_key'])
            if not a:
                continue
            try:
                if job['remote_deal']:
                    remote=api.call('GET','/deals/'+job['remote_deal'])
                    state={'QUALIFIED_TO_BUY':'qualified','UNQUALIFIED_TO_BUY':'disqualified',
                           'CLOSED_WON':'won','CLOSED_LOST':'lost'}.get(remote['stage'])
                    stamp=remote.get('stageChangedAt')
                else:
                    remote=api.call('GET','/contacts/'+job['remote_contact'])
                    fields={f['label']:f.get('value') for f in remote['fields']}
                    prefix='SEO '+a['site']+' '
                    if fields.get(prefix+'Application key')!=a['key']:
                        continue
                    state=fields.get(prefix+'Status')
                    stamp=None # Contact field API has no edit timestamp; record observation time.
                if state not in {'qualified','disqualified','won','lost'} or state==a['state']:
                    continue
                event_id='crm-'+digest([a['key'],a['state'],state,stamp or a['updated_at']])
                e={k:a[k] for k in ('site','source','application_id','contact','attribution')}
                if a.get('company'):
                    e['company']=a['company']
                e.update(kind=state,event_id=event_id,
                         occurred_at=stamp or dt.datetime.now(dt.timezone.utc).isoformat())
                store.ingest(e)
                result['observed_changes']+=1
            except (ApiError,ValueError,KeyError,TypeError):
                result['failed']+=1
    return result


def load(path=DEFAULT):
    p = Path(path).resolve()
    if not p.exists() and p.name=='crm-config.json':p=p.with_name('crm-config.example.json')
    c = json.loads(p.read_text())
    if c.get('mode')!='local-pilot':
        raise ValueError('Only local-pilot mode is supported')
    c['_root'] = str(p.parent)
    return c


def secret_values(c):
    return {'intake_key':os.environ.get('SEO_OPERATOR_INTAKE_KEY',''),
            'crm_api_key':os.environ.get('SEO_OPERATOR_CRM_API_KEY',''),
            'owner_id':os.environ.get('SEO_OPERATOR_CRM_OWNER_ID','')}


def main():
    ap = argparse.ArgumentParser(description='Local Comp AI CRM integration pilot')
    ap.add_argument('--config',default=str(DEFAULT))
    sub = ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('report');sub.add_parser('sync');sub.add_parser('serve')
    sub.add_parser('doctor');sub.add_parser('retry');sub.add_parser('pull');sub.add_parser('worker')
    p = sub.add_parser('ingest');p.add_argument('file')
    p = sub.add_parser('backup');p.add_argument('file')
    p = sub.add_parser('restore');p.add_argument('file');p.add_argument('--destination',required=True)
    p = sub.add_parser('import-sales');p.add_argument('file')
    p = sub.add_parser('import-links');p.add_argument('database')
    args = ap.parse_args(); c = load(args.config)
    os.umask(0o077)
    store = Ledger(Path(c['_root'])/c['database'],c.get('site_hosts'))
    try:
        if args.cmd=='ingest':
            values=json.loads(Path(args.file).read_text())
            result=[store.ingest(e) for e in (values if isinstance(values,list) else [values])]
        elif args.cmd=='report':
            result=store.summary();out=Path(c['_root'])/'runtime/report.json'
            out.write_text(json.dumps(result,indent=2)+'\n')
            from .crm_server import static_report
            out.with_suffix('.html').write_text(static_report(result))
            result={'report':str(out),'html':str(out.with_suffix('.html')),'applications':result['applications'],'crm_jobs':result['jobs']}
        elif args.cmd=='backup':result=store.backup(args.file)
        elif args.cmd=='restore':
            target=Path(args.destination)
            if target.exists():raise ValueError('Restore destination must not exist; live replacement is forbidden')
            with sqlite3.connect('file:'+urllib.parse.quote(str(Path(args.file).resolve()))+'?mode=ro',uri=True) as src:
                if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid backup')
                target.parent.mkdir(parents=True,exist_ok=True)
                with sqlite3.connect(target) as dest:src.backup(dest)
            os.chmod(target,0o600);result={'restored_to':str(target),'summary':Ledger(target).summary()}
        elif args.cmd=='retry':
            with store.db:store.db.execute("UPDATE jobs SET next_attempt=0 WHERE status='retry'")
            result={'status':'retries-ready'}
        elif args.cmd=='doctor':
            result={'mode':'local-pilot','ledger':str(store.path),'crm':'not-configured'}
            s=secret_values(c)
            if s.get('crm_api_key'):
                try:CompAI(c['crm_api_url'],s['crm_api_key']).search('contacts','pilot-health-check');result['crm']='connected'
                except ApiError as exc:result['crm']=str(exc)
        elif args.cmd in ('sync','pull','worker'):
            if args.cmd=='worker':
                while True:
                    s=secret_values(c);api=CompAI(c['crm_api_url'],s['crm_api_key'])
                    result={'pull':pull(store,api),'sync':sync(store,api,s.get('owner_id'))}
                    status=Path(c['_root'])/'runtime/worker-status.json'
                    status.write_text(json.dumps(result))
                    time.sleep(10)
            else:
                s=secret_values(c);api=CompAI(c['crm_api_url'],s['crm_api_key'])
                result=pull(store,api) if args.cmd=='pull' else sync(store,api,s.get('owner_id'))
        elif args.cmd=='serve':
            from .crm_server import serve
            serve(c);return
        elif args.cmd=='import-sales':
            from .crm_imports import import_sales
            result=import_sales(store,args.file)
        else:
            from .crm_imports import import_links
            result=import_links(store,args.database)
        print(json.dumps(result,indent=2))
        return int(isinstance(result,dict) and bool(result.get('failed')))
    except (ValueError,RuntimeError,sqlite3.Error) as exc:
        print(json.dumps({'status':'error','reason':str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__}))
        return 1
    finally:
        store.db.close()


if __name__=='__main__':
    raise SystemExit(main())

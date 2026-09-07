import csv,json
from urllib.parse import urlsplit
from .core import fingerprint, now, normalize_url
from .web import fetch,Page

def verify_link(source,target):
    result={'source':source,'target':target,'status':'unknown','links':[],'checked':now()}
    try:
        source_page=Page(source,fetch(source)['text'])
        matches=[x for x in source_page.links if normalize_url(x['url'])==normalize_url(target)]
        result.update(status='observed' if matches else 'not-found',links=matches)
        try:result['target_http_status']=fetch(target)['status']
        except Exception:result['target_http_status']=None
    except Exception:result['status']='unavailable'
    return result

def add(c,store,site,source,target,rationale,draft=''):
    if urlsplit(target).netloc!=urlsplit(c['sites'][site]['base_url']).netloc:raise ValueError('Target must belong to selected site')
    if urlsplit(source).netloc==urlsplit(target).netloc:raise ValueError('Prospect must be external')
    if not rationale.strip():raise ValueError('Relevance rationale required')
    identity=fingerprint([site,normalize_url(source),normalize_url(target)])[:20]
    observed=verify_link(source,target)
    state='observed' if observed['status']=='observed' else 'review'
    store.execute('''INSERT INTO prospects VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET rationale=excluded.rationale,draft=excluded.draft,observed=excluded.observed,checked=excluded.checked,status=excluded.status''',(identity,site,source,target,rationale,draft,state,json.dumps(observed),now()))
    return {'id':identity,'state':state,'observation':observed,'sending':'Not implemented; explicit authorization is required'}

def import_links(c,store,site,path):
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not {'source_url','target_url'}.issubset(reader.fieldnames or []):raise ValueError('Normalize GSC export to source_url,target_url columns; site-only exports cannot verify page links')
        result=[add(c,store,site,r['source_url'],r['target_url'],r.get('rationale') or 'Imported Search Console link sample',r.get('draft','')) for r in reader]
    return {'imported':len(result),'coverage':'Sampled; not a complete backlink index'}

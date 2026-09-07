from __future__ import annotations
import concurrent.futures, json, time, xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from .core import now, normalize_url
from .web import fetch, Page, FetchError

UA='SEO-Operator/0.1'

def sitemap_urls(url, host, seen=None):
    seen=seen if seen is not None else set()
    if url in seen or len(seen)>=20:return []
    if urlsplit(url).netloc!=host: return []
    seen.add(url);root=ET.fromstring(fetch(url)['text']);out=[]
    for node in root:
        loc=next((x.text for x in node if x.tag.rsplit('}',1)[-1]=='loc'),None)
        if not loc:continue
        if root.tag.endswith('sitemapindex'):out.extend(sitemap_urls(loc,host,seen))
        elif urlsplit(loc).netloc==host:out.append(normalize_url(loc))
    return list(dict.fromkeys(out))

def inspect(url):
    try:
        response=fetch(url);page=Page(response['url'],response['text']);d=page.document();issues=[]
        if not page.title.strip():issues.append('missing-title')
        if len(page.h1)!=1:issues.append('h1-count:'+str(len(page.h1)))
        if not page.description.strip():issues.append('missing-description')
        if not page.canonical:issues.append('missing-canonical')
        elif normalize_url(page.canonical)!=normalize_url(response['url']):issues.append('canonical-other-url')
        if 'noindex' in page.robots.lower() or 'noindex' in response['headers'].get('x-robots-tag','').lower():issues.append('noindex')
        if not page.lang:issues.append('missing-language')
        if any('error' in s for s in page.schema if isinstance(s,dict)):issues.append('invalid-json-ld')
        d.update(status=response['status'],issues=issues,checked=now(),rendering='initial HTML only; JS rendering and field CWV require separate checks')
        return d
    except Exception as e:return {'url':url,'status':None,'issues':[str(e) if isinstance(e,FetchError) else type(e).__name__],'checked':now(),'links':[]}

def crawl(c,store,site,limit=500):
    base=c['sites'][site]['base_url'];host=urlsplit(base).netloc
    try:
        robots=fetch(base+'/robots.txt')['text'];rp=RobotFileParser();rp.parse(robots.splitlines())
    except Exception:
        store.coverage(site,'crawl','', 'pending','robots.txt unavailable; crawl deferred');return {'status':'pending'}
    try: urls=sitemap_urls(base+'/sitemap.xml',host)
    except Exception:
        store.coverage(site,'crawl','', 'pending','Sitemap unavailable');return {'status':'pending'}
    selected=[u for u in urls if rp.can_fetch(UA,u)][:limit]
    documents=[]
    # Batches cap concurrent load; pause between batches on owned sites.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for i in range(0,len(selected),3):
            for d in pool.map(inspect,selected[i:i+3]):
                documents.append(d);store.execute('INSERT OR REPLACE INTO pages VALUES(?,?,?,?)',(site,d['url'],now(),json.dumps(d)))
            if i+3<len(selected):time.sleep(.25)
    coverage='complete' if len(selected)==len(urls) else 'partial'
    store.coverage(site,'crawl','',coverage,f'{len(selected)}/{len(urls)} sitemap URLs; initial HTML only')
    return {'status':coverage,'sitemap_urls':len(urls),'checked':len(documents),'pages_with_issues':sum(bool(d['issues']) for d in documents)}

def inventory(store,site):
    docs=[json.loads(r['document']) for r in store.rows('SELECT document FROM pages WHERE site=?',(site,))]
    incoming=defaultdict(set);titles=defaultdict(list)
    for d in docs:
        if d.get('title'):titles[d['title']].append(d['url'])
        for link in d.get('links',[]):incoming[normalize_url(link['url'])].add(d['url'])
    return {'pages':len(docs),'duplicate_titles':{k:v for k,v in titles.items() if len(v)>1}, 'no_observed_inlinks':[d['url'] for d in docs if not incoming[normalize_url(d['url'])]], 'issues':[{'url':d['url'],'issues':d['issues']} for d in docs if d.get('issues')], 'qualification':'Inlinks limited to fetched sitemap pages; duplicate titles are review candidates, not deletion instructions.'}

from __future__ import annotations
import datetime as dt, json, re
from collections import defaultdict
from .core import fingerprint, now, final_date

# Transparent prioritization heuristic, not a ranking probability or traffic forecast.
def relevance(query,site):
    q=query.casefold()
    return 3 if any(x in q for x in site['focus']) else 1

def branded(query,site):
    return any(re.search(r'(?<!\w)'+re.escape(b)+r'(?!\w)',query.casefold()) for b in site['brands'])

def discover(c,store,end=None):
    end=end or final_date();start=end-dt.timedelta(days=27);previous=start-dt.timedelta(days=28)
    results={}
    for site,s in c['sites'].items():
        coverage=store.rows("SELECT day,status FROM coverage WHERE site=? AND kind='gsc' AND day>=? AND day<=?",(site,start.isoformat(),end.isoformat()))
        complete=len(coverage)==28 and all(x['status']=='complete' for x in coverage)
        fresh=(final_date()-end).days<=7
        mode='complete' if complete and fresh else 'partial-or-stale'
        current=store.rows('''SELECT query,page,country,device,SUM(clicks) clicks,SUM(impressions) impressions,
        SUM(position*impressions)/NULLIF(SUM(impressions),0) position FROM search_rows
        WHERE site=? AND day>=? AND day<=? AND country='nld' GROUP BY query,page,country,device''',(site,start.isoformat(),end.isoformat()))
        old={ (x['query'],x['page'],x['country'],x['device']):x for x in store.rows('''SELECT query,page,country,device,SUM(clicks) clicks,SUM(impressions) impressions,
        SUM(position*impressions)/NULLIF(SUM(impressions),0) position FROM search_rows WHERE site=? AND day>=? AND day<? GROUP BY query,page,country,device''',(site,previous.isoformat(),start.isoformat()))}
        duplicates=defaultdict(set)
        for r in current:duplicates[(r['query'],r['country'],r['device'])].add(r['page'])
        store.execute("UPDATE opportunities SET status='superseded' WHERE site=? AND status IN ('open','pending-data')",(site,))
        found=[]
        for r in current:
            if branded(r['query'],s) or not r['position'] or not 4<=r['position']<=20:continue
            business=relevance(r['query'],s)
            if r['impressions']<c['min_impressions'] and business<3:continue
            kind='near-miss' if r['impressions']>=c['min_impressions'] else 'low-volume-discovery'
            p=store.rows('SELECT document FROM pages WHERE site=? AND url=?',(site,r['page']))
            page=json.loads(p[0]['document']) if p else {}
            diagnosis=list(page.get('issues',[]))
            if len(duplicates[(r['query'],r['country'],r['device'])])>1:diagnosis.append('multiple-ranking-pages:compare-intent-before-consolidating')
            if not diagnosis:diagnosis=['content-and-internal-link-review-needed']
            fixable=any(x in ('missing-title','missing-description','missing-canonical') for x in diagnosis)
            score=round(business * r['impressions'] * (21-r['position'])/17 * (1.2 if fixable else 1),2)
            identity=fingerprint([site,r['query'],r['page'],r['country'],r['device']])[:20]
            evidence={**r,'start':start.isoformat(),'end':end.isoformat(),'data_status':mode,'prior':old.get((r['query'],r['page'],r['country'],r['device'])), 'diagnosis':diagnosis,'business_relevance':business,'review_after':(end+dt.timedelta(days=28)).isoformat(),'measurement':'Average GSC position; impressions are not search volume. No causal attribution.'}
            status='open' if complete and fresh else 'pending-data'
            store.execute('''INSERT INTO opportunities(id,site,page,query,kind,score,evidence,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,score=excluded.score,evidence=excluded.evidence,status=CASE WHEN opportunities.status IN ('done','in-progress') THEN opportunities.status ELSE excluded.status END,updated=excluded.updated''',(identity,site,r['page'],r['query'],kind,score,json.dumps(evidence),status,now(),now()))
            found.append(identity)
        results[site]={'opportunities':len(found),'data_status':mode,'observed_days':len(coverage),'threshold':c['min_impressions']}
        store.coverage(site,'near-miss','', 'complete' if complete and fresh else 'pending',f'{len(coverage)}/28 days; {len(found)} candidates')
    return results

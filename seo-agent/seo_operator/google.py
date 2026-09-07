from __future__ import annotations
import csv, datetime as dt, json
from urllib.parse import quote
from .core import final_date, now, secrets, normalize_url

SCOPES=['https://www.googleapis.com/auth/webmasters.readonly','https://www.googleapis.com/auth/analytics.readonly']

class Google:
    def __init__(self):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.credentials import Credentials
        sec=secrets(); token_path=sec.get('GOOGLE_OAUTH_TOKEN_FILE')
        if token_path:creds=Credentials.from_authorized_user_file(token_path,SCOPES)
        else:
            path=sec.get('GOOGLE_APPLICATION_CREDENTIALS')
            creds,_=google.auth.load_credentials_from_file(path,scopes=SCOPES) if path else google.auth.default(scopes=SCOPES)
        self.session=AuthorizedSession(creds)
    def request(self,url,body=None):
        r=self.session.request('POST' if body is not None else 'GET',url,json=body,timeout=40)
        if r.status_code!=200:raise RuntimeError(f'Google HTTP {r.status_code}')
        return r.json()
    def sites(self):return self.request('https://www.googleapis.com/webmasters/v3/sites').get('siteEntry',[])
    def query(self,prop,day):
        url='https://www.googleapis.com/webmasters/v3/sites/'+quote(prop,safe='')+'/searchAnalytics/query'
        rows=[];offset=0
        while True:
            batch=self.request(url,{'startDate':day,'endDate':day,'dimensions':['query','page','country','device'], 'type':'web','dataState':'final','rowLimit':25000,'startRow':offset}).get('rows',[])
            rows.extend(batch);offset+=len(batch)
            if len(batch)<25000:break
            if offset>=50000:return rows,True
        return rows,False
    def ga4(self,prop,day,event):
        prop=str(prop).removeprefix('properties/')
        if not prop.isdigit():raise ValueError('GA4 property must be numeric')
        url=f'https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport'
        base={'dateRanges':[{'startDate':day,'endDate':day}], 'dimensions':[{'name':'landingPagePlusQueryString'}], 'dimensionFilter':{'filter':{'fieldName':'sessionDefaultChannelGroup','stringFilter':{'matchType':'EXACT','value':'Organic Search'}}}, 'limit':10000}
        # Sessions and conversions are fetched independently to avoid filtering away non-converters.
        def paged(body):
            out=[];offset=0
            while True:
                response=self.request(url,{**body,'offset':offset});rows=response.get('rows',[]);out.extend(rows);offset+=len(rows)
                if offset>=int(response.get('rowCount',0)) or not rows:return out
        sessions=paged({**base,'metrics':[{'name':'sessions'}]})
        conversions=paged({**base,'metrics':[{'name':'keyEvents'}], 'dimensionFilter':{'andGroup':{'expressions':[base['dimensionFilter'],{'filter':{'fieldName':'eventName','stringFilter':{'matchType':'EXACT','value':event}}}]}}})
        result={r['dimensionValues'][0]['value']:{'sessions':float(r['metricValues'][0]['value']),'conversions':0} for r in sessions}
        for r in conversions:result.setdefault(r['dimensionValues'][0]['value'],{'sessions':0,'conversions':0})['conversions']=float(r['metricValues'][0]['value'])
        return result

def save_day(store,site,day,rows,capped=False):
    if dt.date.fromisoformat(day)>final_date():raise ValueError('Only complete dates (at least three days old) may be imported')
    values=[]
    for r in rows:
        query,page,country,device=r['keys']
        clicks=float(r['clicks']);impressions=float(r['impressions']);position=float(r['position'])
        import math
        if not all(math.isfinite(x) for x in (clicks,impressions,position)) or min(clicks,impressions,position)<0 or clicks>impressions:raise ValueError('Invalid search metrics')
        values.append((site,day,query,normalize_url(page),country.lower(),device.lower(),clicks,impressions,position))
    with store.db:
        store.db.execute('DELETE FROM search_rows WHERE site=? AND day=?',(site,day))
        store.db.executemany('INSERT INTO search_rows VALUES(?,?,?,?,?,?,?,?,?)',values)
        store.db.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?,?,?,?)',(site,'gsc',day,'partial' if capped else 'complete','Top rows only; anonymized queries omitted'+('; row cap reached' if capped else ''),now()))

def import_csv(store,site,path):
    # Explicit daily export contract; ordinary aggregated UI exports cannot establish daily completeness.
    with open(path,newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        required={'date','query','page','country','device','clicks','impressions','position'}
        if not required.issubset(reader.fieldnames or []):raise ValueError('CSV requires '+', '.join(sorted(required)))
        groups={}
        for r in reader:groups.setdefault(r['date'],[]).append({'keys':[r[x] for x in ['query','page','country','device']],**{x:r[x] for x in ['clicks','impressions','position']}})
    for day,rows in groups.items():save_day(store,site,day,rows,True)
    return {'days':len(groups),'rows':sum(map(len,groups.values())),'coverage':'partial: CSV imports do not prove full extraction'}

def sync(c,store,days=7):
    try:g=Google()
    except Exception as e:
        for site in c['sites']:store.coverage(site,'google-access','', 'pending','Configure Google OAuth or service-account access')
        return {'status':'pending','reason':'Google credentials unavailable','error_type':type(e).__name__}
    results={}
    for site,s in c['sites'].items():
        results[site]={}
        for offset in range(days):
            day=(final_date()-dt.timedelta(days=offset)).isoformat()
            try:
                rows,capped=g.query(s['gsc_property'],day);save_day(store,site,day,rows,capped)
                store.coverage(site,'google-access','', 'complete','Read access verified')
            except Exception as e:
                store.coverage(site,'gsc',day,'pending',type(e).__name__);results[site]['gsc']='pending';break
        else:results[site]['gsc']='complete'
        if not s.get('ga4_property'):
            store.coverage(site,'ga4','', 'pending','GA4 property ID required');results[site]['ga4']='pending';continue
        for offset in range(days):
            day=(final_date()-dt.timedelta(days=offset)).isoformat()
            try:
                rows=g.ga4(s['ga4_property'],day,s['conversion_event'])
                with store.db:
                    store.db.execute('DELETE FROM analytics WHERE site=? AND day=?',(site,day))
                    store.db.executemany('INSERT INTO analytics VALUES(?,?,?,?,?)',[(site,day,p,v['sessions'],v['conversions']) for p,v in rows.items()])
                store.coverage(site,'ga4',day,'complete','Configured key event; qualification must be checked in CRM')
            except Exception as e:store.coverage(site,'ga4',day,'pending',type(e).__name__);results[site]['ga4']='pending';break
        else:results[site]['ga4']='complete'
    return results

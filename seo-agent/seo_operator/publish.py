from __future__ import annotations
import datetime as dt, html, json, subprocess
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from .content import validate, render_markdown
from .core import now, secrets, write_json, normalize_url
from .web import json_request, fetch, Page

FIELDS=('title','slug','excerpt','body','category','status','publishedAt','author','language')

class Payload:
    def __init__(self,site,request=json_request):
        self.site=site;self.request=request
        key=secrets().get('PAYLOAD_API_KEY')
        if not key:raise RuntimeError('Payload API key not configured')
        self.headers={'Authorization':'users API-Key '+key}
    def api(self,path,method='GET',data=None):
        return self.request(self.site['base_url']+'/api/'+path,method=method,data=data,headers=self.headers,retries=0 if method!='GET' else 2)
    def identity(self):
        user=self.api('users/me').get('user')
        if not user or user.get('email')!=self.site['payload_identity']:raise RuntimeError('Unexpected Payload identity')
        return True
    def find(self,slug):
        docs=self.api('posts?limit=2&depth=0&where[slug][equals]='+quote(slug,safe='')).get('docs',[])
        if len(docs)>1:raise RuntimeError('Multiple posts have the same slug')
        return docs[0] if docs else None
    def save(self,doc,status,remote_id=None):
        payload={k:doc[k] for k in FIELDS if k in doc};payload['status']=status
        response=self.api('posts'+('/'+str(remote_id) if remote_id else ''), 'PATCH' if remote_id else 'POST',payload)
        return response.get('doc',response)
    def rollback(self,remote_id,previous):
        if previous:self.save(previous,previous['status'],remote_id)
        else:self.api('posts/'+str(remote_id),'PATCH',{'status':'draft'})

class Static:
    def __init__(self,c,site):self.c=c;self.site=site
    def package(self,doc,identity):
        root=Path(self.c['_runtime'])/'packages'/identity
        guides=self.site.get('guides_path','/guides').strip('/')
        language=self.site.get('language',doc.get('language','en'))
        organization=self.site.get('organization_name','Example Organization')
        title=self.site.get('site_title','Example Site')
        dest=root/guides/doc['slug']/'index.html'
        url=self.site['base_url']+'/'+guides+'/'+doc['slug']
        ld={'@context':'https://schema.org','@type':'Article','headline':doc['title'],'description':doc['excerpt'],'inLanguage':language,'datePublished':doc['publishedAt'],'author':{'@type':'Organization','name':organization},'mainEntityOfPage':url}
        markup=f'''<!doctype html><html lang="{html.escape(language)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(doc['title'])} — {html.escape(title)}</title><meta name="description" content="{html.escape(doc['excerpt'],quote=True)}"><link rel="canonical" href="{url}"><meta name="robots" content="index,follow"><style>main.seo-guide{{max-width:760px;margin:4rem auto;padding:0 24px;line-height:1.75}}.seo-guide h1{{line-height:1.15}}.seo-guide img{{max-width:100%}}</style><script type="application/ld+json">{json.dumps(ld,ensure_ascii=False).replace('<', chr(92)+'u003c')}</script></head><body><main class="seo-guide"><nav><a href="/{guides}">Guides</a> / {html.escape(doc['title'])}</nav><article><h1>{html.escape(doc['title'])}</h1><p>{html.escape(doc['excerpt'])}</p>{render_markdown(doc['body'])}</article></main></body></html>'''
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(markup)
        write_json(root/'manifest.json',{'content_id':identity,'url':url,'title':doc['title'],'file':str(dest.relative_to(root)),'required_integration':['Add URL to sitemap.xml','Add a contextual link from the guides index','Run project checks and browser checks','Deploy through a verified production target only']})
        return root
    def deploy(self,package):
        command=self.site.get('deploy_command',[])
        if not self.site.get('deployment_verified') or not command:raise RuntimeError('Static deployment target not verified')
        if not self.site.get('rollback_command'):raise RuntimeError('Static rollback command required')
        result=subprocess.run([x.replace('{package}',str(package)) for x in command],cwd=self.c['_root'],capture_output=True,timeout=600)
        if result.returncode:raise RuntimeError('Deployment command failed; output retained by deployment provider')
    def rollback(self,package):
        command=self.site.get('rollback_command',[])
        if not command:raise RuntimeError('Static rollback is not configured')
        result=subprocess.run([x.replace('{package}',str(package)) for x in command],cwd=self.c['_root'],capture_output=True,timeout=600)
        if result.returncode:raise RuntimeError('Static rollback failed')

def verify(site,doc):
    path=site.get('content_path','/blog').rstrip('/')+'/'+doc['slug'] if site['publisher']=='payload' else '/'+site.get('guides_path','/guides').strip('/')+'/'+doc['slug']
    url=site['base_url']+path
    response=fetch(url)
    p=Page(url,response['text'])
    if normalize_url(p.canonical)!=normalize_url(url):raise RuntimeError('Public canonical mismatch')
    if len(p.h1)!=1 or p.h1[0].strip()!=doc['title'].strip():raise RuntimeError('Public H1 mismatch')
    if not p.lang.startswith(doc['language']):raise RuntimeError('Public document language mismatch')
    if 'noindex' in p.robots.lower() or 'noindex' in response.get('headers',{}).get('x-robots-tag','').lower():raise RuntimeError('Published page is noindex')
    text=' '.join(p.text);body=Page(url,render_markdown(doc['body']))
    # Compare all paragraphs/headings after whitespace normalization, not merely a title.
    for fragment in body.text:
        if len(fragment)>30 and ' '.join(fragment.split()) not in text:raise RuntimeError('Published body does not match staged content')
    from .audit import sitemap_urls
    from urllib.parse import urlsplit
    if normalize_url(url) not in sitemap_urls(site['base_url']+'/sitemap.xml',urlsplit(url).netloc):raise RuntimeError('Published URL absent from sitemap')
    index=site['base_url']+(site.get('content_path','/blog') if site['publisher']=='payload' else '/'+site.get('guides_path','/guides').strip('/'))
    links=Page(index,fetch(index)['text']).links
    if not any(normalize_url(x['url'])==normalize_url(url) for x in links):raise RuntimeError('Published URL absent from discovery index')
    return {'url':url,'verified':now()}

def publish(c,store,identity,client_factory=Payload,verifier=verify):
    rows=store.rows('SELECT * FROM content WHERE id=?',(identity,))
    if not rows:raise ValueError('Unknown content ID')
    row=rows[0];doc=json.loads(row['document']);site=c['sites'][row['site']]
    if row['state']=='published':return {'state':'published','unchanged':True}
    if row['state']=='rollback-failed':raise RuntimeError('Resolve rollback failure before retry')
    checks=validate(c,store,doc,online=True)
    if not checks['passed']:return {'state':'pending-quality','checks':checks}
    if site['publisher']=='disabled':
        return {'state':'pending-setup','reasons':['Publisher disabled in configuration']}
    if site['publisher']=='static':
        adapter=Static(c,site);package=adapter.package(doc,identity)
    reasons=[]
    if not c.get('handover_complete'):reasons.append('External SEO handover unconfirmed')
    if not c.get('publishing_enabled'):reasons.append('Production publishing not enabled')
    if not site.get('language_ready'):reasons.append('Configured language rendering/schema not deployed')
    if site['publisher']=='static' and not site.get('deployment_verified'):reasons.append('Static deployment unverified')
    if reasons:return {'state':'pending-setup','reasons':reasons,**({'package':str(package)} if site['publisher']=='static' else {})}
    if dt.datetime.fromisoformat(doc['publishedAt'].replace('Z','+00:00'))>dt.datetime.now(dt.timezone.utc):return {'state':'scheduled','date':doc['publishedAt']}
    week=dt.datetime.now(ZoneInfo(c['timezone'])).date();week-=dt.timedelta(days=week.weekday())
    prior_publications=store.rows('SELECT id FROM publications WHERE content_id=?',(identity,))
    prior_snapshot=json.loads(row['previous']) if row['previous'] else {}
    kind='update' if prior_publications or prior_snapshot.get('status')=='published' else 'new'
    count=store.rows('SELECT COUNT(*) n FROM publications WHERE site=? AND kind=? AND published>=?',(row['site'],kind,dt.datetime.combine(week,dt.time(),ZoneInfo(c['timezone'])).astimezone(dt.timezone.utc).isoformat()))[0]['n']
    if count>=c['weekly_update_limit' if kind=='update' else 'weekly_new_limit']:return {'state':'pending-budget'}
    previous=json.loads(row['previous']) if row['previous'] else None;remote_id=row['remote_id']
    client=None;attempted=False
    try:
        if site['publisher']=='payload':
            client=client_factory(site);client.identity();existing=client.find(doc['slug'])
            if existing and not remote_id:
                # Reconcile an interrupted create only if the draft is byte-for-byte our own content.
                if existing.get('status')!='draft' or any(existing.get(k)!=doc.get(k) for k in ('title','body','excerpt','language')):raise RuntimeError('Slug belongs to an untracked remote post; import it explicitly before editing')
                remote_id=str(existing['id'])
            if existing and remote_id and str(existing['id'])!=str(remote_id):raise RuntimeError('Remote ID conflict')
            if existing and existing.get('status')=='published' and row['state']=='publishing' and all(existing.get(k)==doc.get(k) for k in ('title','body','excerpt','language')):
                attempted=True
                result=verifier(site,doc)
            else:
                if existing and existing.get('status')=='published':
                    versions=store.rows('SELECT document FROM versions WHERE content_id=? ORDER BY id DESC LIMIT 1',(identity,))
                    expected=json.loads(versions[0]['document']) if versions else previous
                    if expected and any(existing.get(k)!=expected.get(k) for k in ('body','title','excerpt')):
                        raise RuntimeError('Remote content changed outside Hermes; reconcile before updating')
                    previous={k:existing[k] for k in FIELDS if k in existing}
                store.execute("UPDATE content SET state='publishing',previous=?,updated=? WHERE id=?",(json.dumps(previous) if previous else None,now(),identity))
                if not remote_id:
                    new=client.save(doc,'draft');remote_id=str(new['id'])
                    store.execute('UPDATE content SET remote_id=? WHERE id=?',(remote_id,identity))
                    if new.get('language')!=doc['language']:raise RuntimeError('Payload did not persist language field')
                attempted=True;client.save(doc,'published',remote_id);result=verifier(site,doc)
        else:
            store.execute("UPDATE content SET state='publishing',updated=? WHERE id=?",(now(),identity))
            attempted=True;adapter.deploy(package);result=verifier(site,doc)
        with store.db:
            store.db.execute("UPDATE content SET state='published',remote_id=?,updated=? WHERE id=?",(remote_id,now(),identity))
            store.db.execute('INSERT OR IGNORE INTO publications(content_id,revision,site,kind,published) VALUES(?,?,?,?,?)',(identity,row['revision'],row['site'],kind,now()))
        return {'state':'published',**result}
    except Exception as exc:
        rollback='not-needed'
        if attempted:
            try:
                if client:client.rollback(remote_id,previous)
                else:adapter.rollback(package)
                rollback='restored'
            except Exception:rollback='failed'
        state='rollback-failed' if rollback=='failed' else 'staged'
        store.execute('UPDATE content SET state=?,updated=? WHERE id=?',(state,now(),identity))
        return {'state':state,'error':str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__,'rollback':rollback}

def import_remote(c,store,site,slug):
    from .core import fingerprint
    client=Payload(c['sites'][site]);client.identity();doc=client.find(slug)
    if not doc:raise ValueError('Remote post not found')
    identity=fingerprint([site,slug])[:20]
    if store.rows('SELECT id FROM content WHERE id=?',(identity,)):raise RuntimeError('Content already tracked')
    previous={k:doc[k] for k in FIELDS if k in doc};local={**previous,'site':site}
    store.execute('INSERT INTO content VALUES(?,?,?,?,?,?,?,?,?)',(identity,site,slug,fingerprint(local),'imported',json.dumps(local),str(doc['id']),json.dumps(previous),now()))
    return {'id':identity,'state':'imported','next':'Prepare a revised brief and pass review before staging'}

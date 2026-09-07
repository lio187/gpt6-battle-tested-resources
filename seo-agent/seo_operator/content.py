from __future__ import annotations
import datetime as dt, json, re
from urllib.parse import urlsplit, urljoin
from .core import fingerprint, now
from .web import Page, fetch

CATEGORIES={'automation','education','ecommerce','customer-support','retention','ops-reporting','integrations','finance','legal','healthcare','news'}

def render_markdown(body):
    from markdown_it import MarkdownIt
    return MarkdownIt('commonmark',{'html':False,'linkify':False}).render(body)

def validate(c,store,doc,online=False):
    errors=[];warnings=[];site=doc.get('site');s=c['sites'].get(site)
    if not s:return {'passed':False,'errors':['Unknown site'],'warnings':[]}
    for field in ['title','slug','excerpt','body','category','publishedAt','query','intent','original_contribution','cta']:
        if not doc.get(field):errors.append('Missing '+field)
    for field in ('sources','claims'):
        if not isinstance(doc.get(field),list):errors.append(field+' must be a list')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',doc.get('slug','')):errors.append('Invalid slug')
    language=s.get('language','en')
    if doc.get('language')!=language:errors.append('Content language must match site configuration')
    if doc.get('category') not in set(c.get('categories',CATEGORIES)):errors.append('Invalid category')
    try:
        stamp=dt.datetime.fromisoformat(doc['publishedAt'].replace('Z','+00:00'))
        if stamp.tzinfo is None:errors.append('publishedAt requires timezone')
    except (KeyError,TypeError,ValueError):errors.append('Invalid publishedAt')
    body=doc.get('body','');html=render_markdown(body);page=Page(s['base_url'],html)
    if page.h1:errors.append('Body must start below H1; page template owns H1')
    if re.search(r'<\s*/?\s*[a-zA-Z][^>]*>',body):errors.append('Raw HTML is not accepted')
    if re.search(r'\b(TODO|TBD|PLACEHOLDER|lorem ipsum)\b',body,re.I):errors.append('Unfinished content')
    # This is a useful language check, not a claim that language alone establishes quality.
    if len(' '.join(page.text))<250:errors.append('Insufficient text to validate language and usefulness')
    else:
        try:
            from langdetect import detect, DetectorFactory
            DetectorFactory.seed=0
            if detect(' '.join(page.text))!=language:errors.append('Primary text does not match the configured language')
        except Exception:errors.append('Language validation unavailable')
    if doc.get('cta') not in [urljoin(s['base_url'],s['conversion_path']),s['conversion_path']]:errors.append('CTA does not match configured conversion route')
    target=urljoin(s['base_url'],doc.get('cta',''))
    if not any(l['url']==target for l in page.links):errors.append('CTA link missing from body')
    internal=[l for l in page.links if urlsplit(l['url']).netloc==urlsplit(s['base_url']).netloc]
    if len({x['url'] for x in internal})<2:errors.append('Add at least two relevant internal destinations including CTA')
    sources=doc.get('sources',[])
    if not isinstance(sources,list):sources=[];errors.append('sources must be a list')
    source_ids={x.get('id') for x in sources if isinstance(x,dict)}
    fetched={}
    for source in sources:
        if not isinstance(source,dict) or not all(source.get(k) for k in ('id','url','accessed_at','supports')):errors.append('Incomplete source record');continue
        if urlsplit(source['url']).scheme!='https':errors.append('Sources must use HTTPS')
        try:
            age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(source['accessed_at'].replace('Z','+00:00'))).days
            if age<0 or age>90:errors.append('Source verification must be within 90 days')
        except ValueError:errors.append('Invalid source access date')
        if online:
            try:fetched[source['id']]=' '.join(Page(source['url'],fetch(source['url'])['text']).text)
            except Exception:errors.append('Source inaccessible: '+source['url'])
    for claim in doc.get('claims',[]):
        if not all(claim.get(k) for k in ('text','source_id','evidence_excerpt')) or claim.get('source_id') not in source_ids:errors.append('Unsupported claim record');continue
        if online and claim.get('source_id') in fetched:
            excerpt=' '.join(claim['evidence_excerpt'].split())
            if excerpt.casefold() not in fetched[claim['source_id']].casefold():errors.append('Evidence excerpt not found for claim: '+claim['text'][:70])
    # Semantic review is performed by Hermes separately and tied to this exact revision.
    review=doc.get('review',{});unsigned={k:v for k,v in doc.items() if k!='review'}
    needed=('factual_support','original_value','intent_match','brand_accuracy','comparison_fairness')
    if review.get('content_hash')!=fingerprint(unsigned) or not all(review.get(k) is True for k in needed) or not review.get('rationale'):
        errors.append('Evidence review missing, failed, or for another revision')
    if doc.get('category') in ('finance','legal','healthcare'):errors.append('Outside initial automatic publishing campaign')
    for r in store.rows('SELECT site,slug,document FROM content'):
        other=json.loads(r['document'])
        if (r['site'],r['slug'])==(site,doc.get('slug')):continue
        if other.get('query','').casefold()==doc.get('query','').casefold():errors.append('Query already assigned to '+r['site']+'/'+r['slug'])
        if fingerprint(other.get('body'))==fingerprint(body):errors.append('Duplicate body across sites')
    if online:
        for link in {x['url'] for x in page.links}:
            if urlsplit(link).scheme not in ('http','https'):errors.append('Unsupported link destination');continue
            try:fetch(link)
            except Exception:errors.append('Broken or unavailable link: '+link)
    else:warnings.append('Offline validation: source evidence and links not fetched')
    return {'passed':not errors,'errors':errors,'warnings':warnings,'revision':fingerprint(doc),'online':online,'checked':now()}

def stage(c,store,doc):
    result=validate(c,store,doc)
    if not result['passed']:return result
    identity=fingerprint([doc['site'],doc['slug']])[:20]
    old=store.rows('SELECT * FROM content WHERE id=?',(identity,))
    revision=fingerprint(doc)
    if old and old[0]['revision']==revision:return {'id':identity,'state':old[0]['state'],'unchanged':True}
    if old and old[0]['state'] in ('publishing','rollback-failed'):raise RuntimeError('Reconcile in-flight publication before changing content')
    with store.db:
        if old:store.db.execute('INSERT INTO versions(content_id,created,document) VALUES(?,?,?)',(identity,now(),old[0]['document']))
        store.db.execute('''INSERT INTO content(id,site,slug,revision,state,document,updated) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,state='staged',document=excluded.document,updated=excluded.updated''',(identity,doc['site'],doc['slug'],revision,'staged',json.dumps(doc),now()))
    return {'id':identity,'state':'staged','validation':result}

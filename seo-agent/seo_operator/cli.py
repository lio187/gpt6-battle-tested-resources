from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from .core import config,Store,lock,write_json,fingerprint
from . import audit,google,opportunities,content,publish,links,report

def doctor(c,store):
    result={}
    try:
        g=google.Google();sites=g.sites();result['google']={'status':'connected','accessible_properties':[s['siteUrl'] for s in sites]}
    except Exception as e:result['google']={'status':'pending','reason':'Configure read-only Google OAuth or service account','error_type':type(e).__name__}
    for site,s in c['sites'].items():
        r={'language_ready':s.get('language_ready'), 'ga4_property_configured':bool(s.get('ga4_property'))}
        if s['publisher']=='payload':
            try:publish.Payload(s).identity();r['authentication']='verified'
            except Exception as e:r['authentication']='pending';r['error_type']=type(e).__name__
        elif s['publisher']=='disabled':r['publisher']='disabled'
        else:r['deployment']='verified' if s.get('deployment_verified') else 'pending authoritative repository/deployment'
        result[site]=r
    result['handover']='complete' if c['handover_complete'] else 'pending'
    result['outreach']='drafts only; no send command'
    write_json(Path(c['_runtime'])/'doctor.json',result)
    return result

def main():
    ap=argparse.ArgumentParser(description='Evidence-backed SEO Operator')
    ap.add_argument('--config');sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor');sub.add_parser('report');sub.add_parser('opportunities')
    for name in ['sync','daily']:
        p=sub.add_parser(name);p.add_argument('--days',type=int,default=7)
    p=sub.add_parser('crawl');p.add_argument('--site');p.add_argument('--limit',type=int,default=500)
    p=sub.add_parser('import-gsc');p.add_argument('--site',required=True);p.add_argument('file')
    p=sub.add_parser('validate');p.add_argument('file');p.add_argument('--online',action='store_true')
    p=sub.add_parser('hash');p.add_argument('file')
    p=sub.add_parser('stage');p.add_argument('file')
    p=sub.add_parser('publish');p.add_argument('id')
    p=sub.add_parser('import-post');p.add_argument('slug');p.add_argument('--site',required=True)
    p=sub.add_parser('package');p.add_argument('file')
    p=sub.add_parser('import-links');p.add_argument('--site',required=True);p.add_argument('file')
    p=sub.add_parser('prospect');p.add_argument('--site',required=True);p.add_argument('--source',required=True);p.add_argument('--target',required=True);p.add_argument('--rationale',required=True);p.add_argument('--draft-file')
    args=ap.parse_args();c=config(args.config)
    if hasattr(args,'site') and args.site and args.site not in c['sites']:
        ap.error('--site must match a key in config.json')
    store=Store(Path(c['_runtime'])/'seo.sqlite3')
    try:
        with lock(c),store.run(args.command):
            if args.command=='doctor':result=doctor(c,store)
            elif args.command=='sync':
                if not 1<=args.days<=480:raise ValueError('days must be 1–480')
                result=google.sync(c,store,args.days)
            elif args.command=='daily':
                if not 1<=args.days<=480:raise ValueError('days must be 1–480')
                result={'sync':google.sync(c,store,args.days),'opportunities':opportunities.discover(c,store),'report':report.report(c,store)}
            elif args.command=='crawl':
                if not 1<=args.limit<=5000:raise ValueError('limit must be 1–5000')
                result={s:audit.crawl(c,store,s,args.limit) for s in ([args.site] if args.site else c['sites'])}
            elif args.command=='opportunities':result=opportunities.discover(c,store)
            elif args.command=='report':result=report.report(c,store)
            elif args.command=='import-gsc':result=google.import_csv(store,args.site,args.file)
            elif args.command in ('validate','stage','package','hash'):
                doc=json.loads(Path(args.file).read_text())
                if args.command=='validate':result=content.validate(c,store,doc,args.online)
                elif args.command=='stage':result=content.stage(c,store,doc)
                elif args.command=='hash':result={'content_hash':fingerprint({k:v for k,v in doc.items() if k!='review'})}
                else:
                    checks=content.validate(c,store,doc)
                    if not checks['passed']:result=checks
                    elif c['sites'][doc['site']]['publisher']!='static':raise ValueError('Package supports static publisher only')
                    else:result={'package':str(publish.Static(c,c['sites'][doc['site']]).package(doc,fingerprint([doc['site'],doc['slug']])[:20]))}
            elif args.command=='publish':result=publish.publish(c,store,args.id)
            elif args.command=='import-post':result=publish.import_remote(c,store,args.site,args.slug)
            elif args.command=='import-links':result=links.import_links(c,store,args.site,args.file)
            else:result=links.add(c,store,args.site,args.source,args.target,args.rationale,Path(args.draft_file).read_text() if args.draft_file else '')
        print(json.dumps(result,indent=2,ensure_ascii=False))
        if isinstance(result,dict) and result.get('passed') is False:return 2
        return 0
    except Exception as e:
        print(json.dumps({'status':'error','type':type(e).__name__,'message':str(e) if isinstance(e,(ValueError,RuntimeError)) else 'Operation failed; inspect local integration configuration'}));return 1

if __name__=='__main__':sys.exit(main())

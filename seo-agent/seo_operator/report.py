import csv,datetime as dt,json
from pathlib import Path
from .audit import inventory
from .core import now,final_date

def report(c,store):
    root=Path(c['_runtime'])/'reports';root.mkdir(parents=True,exist_ok=True)
    lines=['# SEO Operator report', '', 'Generated: '+now(), '', 'Rankings and conversions are observed data, never forecasts.', '']
    export=[]
    end=final_date();start=end-dt.timedelta(days=27)
    for site,s in c['sites'].items():
        lines.extend(['## '+s['base_url'],''])
        coverage=store.rows('SELECT kind,day,status,note FROM coverage WHERE site=? ORDER BY kind,day DESC',(site,))
        by_kind={}
        for row in coverage:by_kind.setdefault(row['kind'],row)
        for kind,row in by_kind.items():lines.append(f"- {kind}: **{row['status']}** — {row['note']}")
        if not coverage:lines.append('- Data connections have not been run.')
        totals=store.rows('SELECT SUM(clicks) clicks,SUM(impressions) impressions FROM search_rows WHERE site=? AND day>=? AND day<=?',(site,start.isoformat(),end.isoformat()))[0]
        lines.extend(['',f"Observed query-row clicks: {totals['clicks'] if totals['clicks'] is not None else 'unavailable'}; impressions: {totals['impressions'] if totals['impressions'] is not None else 'unavailable'}. Query rows omit anonymized data and are not property totals.",''])
        analytics=store.rows('SELECT SUM(sessions) sessions,SUM(conversions) conversions FROM analytics WHERE site=? AND day>=? AND day<=?',(site,start.isoformat(),end.isoformat()))[0]
        lines.append(f"Organic sessions: {analytics['sessions'] if analytics['sessions'] is not None else 'unavailable'}; configured key events: {analytics['conversions'] if analytics['conversions'] is not None else 'unavailable'}. Qualified leads require CRM confirmation; no query-level attribution.")
        opportunities=store.rows("SELECT * FROM opportunities WHERE site=? AND status IN ('open','pending-data','in-progress') ORDER BY score DESC",(site,))
        lines.extend(['','### Near-miss queue',''])
        for row in opportunities[:15]:
            ev=json.loads(row['evidence']);lines.append(f"- [{row['query']}]({row['page']}) — {ev['device']}, position {ev['position']:.1f}, {ev['impressions']:.0f} impressions; {row['status']}. Diagnosis: {', '.join(ev['diagnosis'])}.")
        if not opportunities:lines.append('No verified candidates available. Connect Search Console; absence of data does not mean absence of opportunities.')
        export.extend([{k:r[k] for k in ('id','site','query','page','kind','score','status','evidence')} for r in opportunities])
        audit=inventory(store,site);lines.extend(['','### Technical observations','',f"{audit['pages']} stored pages. {len(audit['duplicate_titles'])} duplicate-title groups. {audit['qualification']}"])
        for row in audit['issues'][:20]:lines.append(f"- [{row['url']}]({row['url']}): {', '.join(row['issues'])}")
        write=(root/(site+'-audit.json'));write.write_text(json.dumps(audit,indent=2,ensure_ascii=False))
        lines.extend(['','### Production and links',''])
        for row in store.rows('SELECT slug,state FROM content WHERE site=?',(site,)):lines.append(f"- Content `{row['slug']}`: {row['state']}")
        counts=store.rows('SELECT status,COUNT(*) n FROM prospects WHERE site=? GROUP BY status',(site,))
        lines.append('Link queue: '+(', '.join(f"{r['n']} {r['status']}" for r in counts) or 'empty')+'. Outreach is not sent automatically.')
        lines.append('')
    lines.extend(['## Activation dependencies','', '- External producer handover: '+('confirmed' if c.get('handover_complete') else 'pending'),'- Automatic publication: '+('enabled' if c.get('publishing_enabled') else 'pending readiness checks'),'', 'Review windows: compare 28 complete days, matched countries/devices and seasonal history. Do not infer causation from a simple before/after change.'])
    pilot_path = c.get('crm_report')
    if pilot_path:
        path = Path(c['_root']) / pilot_path
        lines.extend(['', '## Local CRM pilot', '', 'Pilot data is separate from production SEO results. Sources named pilot-demo contain synthetic test events.'])
        if path.exists():
            try:
                pilot = json.loads(path.read_text())
                if pilot.get('mode') != 'local-pilot':
                    raise ValueError('Unexpected CRM report mode')
                lines.append(f"Local ledger: {pilot['applications']} applications; CRM queue: {json.dumps(pilot['jobs'])}. This does not verify a running Comp AI installation.")
                lines.append(f"Pilot report: {path.with_suffix('.html')}. Updated independently by the local CRM adapter.")
            except (ValueError, KeyError, TypeError):
                lines.append('CRM pilot report could not be validated; no CRM metrics imported.')
        else:
            lines.append('CRM pilot report has not been generated.')
    (root/'latest.md').write_text('\n'.join(lines)+'\n')
    with (root/'opportunities.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['id','site','query','page','kind','score','status','evidence']);w.writeheader();w.writerows(export)
    return {'report':str(root/'latest.md'),'csv':str(root/'opportunities.csv')}

"""Read-only imports: preserve original source IDs and never infer SEO attribution."""
import json, sqlite3, urllib.parse
from pathlib import Path
import re


def sales_mapping(store):
    exists = store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sales_snapshot'").fetchone()
    if not exists:
        return {'records':0,'company_candidates':0,'manual_review':0,'rows':[]}
    rows = []
    for source_id, document in store.db.execute('SELECT source_id,document FROM sales_snapshot ORDER BY source_id'):
        doc = json.loads(document); company = doc.get('company') or {}; domain = company.get('domain')
        valid_domain = isinstance(domain,str) and bool(re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+',domain.lower()))
        candidate = bool(company.get('name')) and valid_domain and doc.get('contact') is None
        rows.append({'source_id':source_id,'source_stage':doc.get('stage'),'crm_stage':None,
                     'mapping':'company-candidate' if candidate else 'manual-review',
                     'reason':'No identified person; do not infer a contact or sales outcome' if candidate else 'Company identity or domain needs review'})
    return {'records':len(rows),'company_candidates':sum(r['mapping']=='company-candidate' for r in rows),
            'manual_review':sum(r['mapping']=='manual-review' for r in rows),'rows':rows}


def import_sales(store, filename):
    raw = json.loads(Path(filename).read_text())
    if not isinstance(raw,dict) or not isinstance(raw.get('docs'),list):
        raise ValueError('Expected Payload sales-leads export with docs array')
    store.db.execute('''CREATE TABLE IF NOT EXISTS sales_snapshot(
        source_id TEXT PRIMARY KEY, document TEXT NOT NULL)''')
    ids = []
    with store.db:
        for doc in raw['docs']:
            if not isinstance(doc,dict) or not isinstance(doc.get('id'),(str,int)):
                raise ValueError('Sales record must have a source id')
            source_id = str(doc['id'])
            store.db.execute('INSERT OR REPLACE INTO sales_snapshot VALUES(?,?)',(source_id,json.dumps(doc)))
            ids.append(source_id)
    return {'imported':len(ids),'source_ids':ids,'production_writes':0,
            'attribution':'unknown; sales records are not automatically SEO applications',
            'mapping_validation':sales_mapping(store),
            'next':'Reconcile source stages and contact identity before CRM migration'}


def import_links(store, database):
    path=Path(database).resolve(strict=True)
    with sqlite3.connect('file:'+urllib.parse.quote(str(path))+'?mode=ro',uri=True) as src:
        src.row_factory=sqlite3.Row
        rows=[dict(r) for r in src.execute('SELECT * FROM prospects')]
    with store.db:
        for row in rows:
            # observed is evidence from the SEO link checker, not an outreach promise.
            row['send_status']='draft-only'
            store.db.execute('INSERT OR REPLACE INTO link_prospects VALUES(?,?)',(row['id'],json.dumps(row)))
    return {'imported':len(rows),'production_writes':0,'outreach':'draft-only'}

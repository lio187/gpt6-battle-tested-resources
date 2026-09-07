#!/usr/bin/env python3
"""Apply a staged guide to an explicitly selected site checkout, with reversible backups.

Does not deploy. Refuses dirty Git checkouts to prevent bundling unrelated edits.
"""
import argparse,html,json,shutil,subprocess,xml.etree.ElementTree as ET
from pathlib import Path

NS='http://www.sitemaps.org/schemas/sitemap/0.9'

def integrate(package,repo,check_git=True):
    package=Path(package).resolve();repo=Path(repo).resolve();m=json.loads((package/'manifest.json').read_text())
    if check_git:
        root=subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=repo,text=True).strip()
        if Path(root).resolve()!=repo:raise RuntimeError('Select the authoritative site repository, not an untracked export in a parent repository')
        if subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip():raise RuntimeError('Checkout has existing changes; use a clean isolated checkout')
    source=(package/m['file']).resolve()
    if not source.is_relative_to(package):raise ValueError('Package path escapes artifact')
    rel=Path(m['file'])
    if rel.is_absolute() or '..' in rel.parts or len(rel.parts)<3 or rel.name!='index.html':raise ValueError('Guide package path is invalid')
    index=repo/rel.parents[1]/'index.html';sitemap=repo/'sitemap.xml';dest=(repo/rel).resolve()
    if not dest.is_relative_to(repo):raise ValueError('Destination escapes site')
    original_index=index.read_text();tree=ET.fromstring(sitemap.read_text());ET.register_namespace('',NS)
    if tree.tag!='{'+NS+'}urlset':raise ValueError('Adapter requires URL sitemap; sitemap index needs site-specific integration')
    if '</main>' not in original_index:raise ValueError('Guide index has no main element; adapt template explicitly')
    backup=package/'integration-backup'
    if backup.exists():raise RuntimeError('Existing integration backup found; restore or finish previous integration')
    backup.mkdir()
    targets=[index,sitemap,dest];log=[]
    for target in targets:
        relative=target.relative_to(repo);existed=target.exists();log.append({'path':str(relative),'existed':existed})
        if existed:
            out=backup/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,out)
    (backup/'state.json').write_text(json.dumps({'repo':str(repo),'targets':log},indent=2))
    try:
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
        path='/'+str(rel.parent).replace('\\','/')
        if path not in original_index:
            card=f'<section data-seo-content="{html.escape(m["content_id"],quote=True)}"><h2><a href="{html.escape(path,quote=True)}">{html.escape(m["title"])}</a></h2></section>'
            index.write_text(original_index.replace('</main>',card+'</main>',1))
        urls=[x.text for x in tree.iter('{'+NS+'}loc')]
        if m['url'] not in urls:ET.SubElement(ET.SubElement(tree,'{'+NS+'}url'),'{'+NS+'}loc').text=m['url']
        sitemap.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(tree,encoding='unicode'))
    except Exception:restore(package);raise
    return {'files':[str(x.relative_to(repo)) for x in targets],'backup':str(backup),'deployment':'not performed'}

def restore(package):
    backup=Path(package)/'integration-backup';m=json.loads((backup/'state.json').read_text());repo=Path(m['repo'])
    for item in m['targets']:
        target=(repo/item['path']).resolve()
        if not target.is_relative_to(repo.resolve()):raise ValueError('Invalid restore destination')
        if item['existed']:shutil.copy2(backup/item['path'],target)
        elif target.exists():target.unlink()
    (backup/'restored').write_text('Restored; preserve backup as audit evidence.\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('package');p.add_argument('--repository');p.add_argument('--restore',action='store_true');a=p.parse_args()
    if a.restore:restore(a.package);print('Local integration restored')
    elif not a.repository:p.error('--repository is required')
    else:print(json.dumps(integrate(a.package,a.repository),indent=2))

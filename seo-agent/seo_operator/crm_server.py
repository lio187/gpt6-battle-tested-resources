"""Loopback-only authenticated pilot intake and dashboard; not a public webhook."""
import contextlib, hmac, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from .crm import Ledger, secret_values

PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Local CRM pilot</title>
<style>body{font:16px system-ui;background:#10151c;color:#edf2f7;max-width:1100px;margin:40px auto;padding:24px}input,button{padding:12px;font:inherit}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:14px;border-bottom:1px solid #344050}small{color:#abc}h1{font-size:32px}</style>
<h1>SEO → applications → revenue</h1><p>Local, opt-in CRM adapter</p><small>This pilot does not replace your active sales console and does not report individual search terms.</small>
<p><input id="key" type="password" placeholder="Local intake key" autocomplete="off"><button id="load">Load report</button></p><p id="status"></p><div id="report"></div>
<script>document.getElementById('load').onclick=async()=>{const s=document.getElementById('status');s.textContent='Loading…';try{const r=await fetch('/report',{headers:{Authorization:'Bearer '+document.getElementById('key').value}});if(!r.ok)throw Error('Access denied or report unavailable');const d=await r.json();s.textContent=d.applications+' applications · '+JSON.stringify(d.jobs);const table=document.createElement('table');const headers=['Site','Landing page','Channel','Applications','Qualified','Won','Revenue EUR'];const h=document.createElement('tr');headers.forEach(x=>{const th=document.createElement('th');th.textContent=x;h.append(th)});table.append(h);d.rows.forEach(x=>{const tr=document.createElement('tr');[x.site,x.landing_page,x.channel,x.applications,x.qualified_ever,x.won,(x.revenue_cents/100).toFixed(2)].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});table.append(tr)});document.getElementById('report').replaceChildren(table)}catch(e){s.textContent=e.message}}</script></html>'''


def server(c, port=None):
    dbpath = Path(c['_root']) / c['database']
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,value,html=False):
            payload=value.encode() if html else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(payload)
        def authorized(self):
            # Reload per request: rotating or revoking a key takes effect immediately.
            key=secret_values(c).get('intake_key','')
            value=self.headers.get('Authorization','')
            return bool(key) and hmac.compare_digest(value.encode(),('Bearer '+key).encode())
        def do_GET(self):
            if self.path=='/':return self.reply(200,PAGE,True)
            if self.path=='/health':return self.reply(200,{'status':'ok','mode':'local-pilot'})
            if self.path!='/report':return self.reply(404,{'error':'not-found'})
            if not self.authorized():return self.reply(401,{'error':'unauthorized'})
            with contextlib.closing(Ledger(dbpath,c.get('site_hosts'))) as store:self.reply(200,store.summary())
        def do_POST(self):
            if self.path!='/events':return self.reply(404,{'error':'not-found'})
            if not self.authorized():return self.reply(401,{'error':'unauthorized'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=65536:return self.reply(413,{'error':'size-limit'})
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    return self.reply(415,{'error':'json-required'})
                self.connection.settimeout(5)
                event=json.loads(self.rfile.read(length))
                with contextlib.closing(Ledger(dbpath,c.get('site_hosts'))) as store:result=store.ingest(event)
                self.reply(202 if result['status']=='accepted' else 200,result)
            except (ValueError,UnicodeDecodeError):self.reply(400,{'error':'invalid-event-or-conflict'})
            except TimeoutError:self.reply(408,{'error':'request-timeout'})
    return HTTPServer(('127.0.0.1', c['intake_port'] if port is None else port),Handler)


def serve(c):
    secret_values(c)
    srv=server(c)
    print('Local pilot: http://127.0.0.1:'+str(srv.server_port),flush=True)
    try:srv.serve_forever()
    except KeyboardInterrupt:pass
    finally:srv.server_close()


def static_report(d):
    import html
    esc=lambda v:html.escape(str(v))
    rows=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (
        x['site'],x['source'],x['landing_page'],x['channel'],x['applications'],
        x['qualified_ever'],x['won'],f"{x['revenue_cents']/100:.2f}"))+'</tr>' for x in d['rows'])
    links=''.join('<article><h3>'+esc(x['source_url'])+'</h3><p>Bestemming: '+esc(x['target_url'])+
        '</p><p>Status: '+esc(x['status'])+' · '+esc(x['observed'])+'</p><p>'+esc(x['rationale'])+
        '</p><pre>'+esc(x.get('draft',''))+'</pre></article>' for x in d.get('link_prospects',[]))
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Local CRM pilot</title>
<style>body{font:15px system-ui;max-width:1200px;margin:40px auto;padding:24px;color:#172334}td,th{text-align:left;padding:12px;border-bottom:1px solid #ddd}table{border-collapse:collapse}pre{white-space:pre-wrap}article{border-top:1px solid #ddd;padding:16px 0}</style>
<h1>Local CRM pilot</h1><p>Sources named <b>pilot-demo</b> contain synthetic test data only.</p><p>Revenue counts confirmed payment and refund events only. A won deal is not itself a payment.</p>
<table><tr><th>Site</th><th>Source</th><th>Landing page</th><th>Channel</th><th>Applications</th><th>Qualified</th><th>Won</th><th>Revenue EUR</th></tr>'''+rows+'</table><h2>CRM processing</h2><p>'+esc(json.dumps(d['jobs']))+'</p><h2>Link drafts</h2><p>Nothing was sent automatically.</p>'+links+'</html>'

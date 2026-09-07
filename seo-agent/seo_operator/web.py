from __future__ import annotations
import ipaddress, json, socket, time, urllib.error, urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from .core import normalize_url

class FetchError(RuntimeError): pass

def public_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise FetchError('Only public HTTPS URLs are supported')
    try: addresses = socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
    except OSError: raise FetchError('DNS lookup failed')
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise FetchError('Non-public destination rejected')

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        if req.has_header('Authorization') and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            raise FetchError('Authenticated cross-origin redirect rejected')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url, method='GET', data=None, headers=None, retries=2):
    public_url(url)
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=payload, method=method,
        headers={'User-Agent':'SEO-Operator/0.1', **({'Content-Type':'application/json'} if payload else {}), **(headers or {})})
    for attempt in range(retries+1):
        try:
            with urllib.request.build_opener(Redirect()).open(req,timeout=25) as r:
                raw = r.read(5_000_001)
                if len(raw)>5_000_000: raise FetchError('Response exceeds 5 MB')
                return {'status':r.status,'url':r.url,'headers':{k.lower():v for k,v in r.headers.items()},'text':raw.decode('utf-8',errors='replace')}
        except urllib.error.HTTPError as e:
            if method=='GET' and e.code in (429,500,502,503,504) and attempt<retries:
                time.sleep(2**attempt);continue
            # Never include bodies or headers: auth errors may echo sensitive data.
            raise FetchError(f'HTTP {e.code}') from None
        except (OSError,urllib.error.URLError):
            if method=='GET' and attempt<retries:time.sleep(2**attempt);continue
            raise FetchError('Network request failed') from None

def json_request(url, **kwargs):
    return json.loads(fetch(url,**kwargs)['text'])

class Page(HTMLParser):
    def __init__(self, url, html):
        super().__init__(convert_charrefs=True)
        self.url=url;self.title='';self.h1=[];self.lang='';self.canonical='';self.description='';self.robots='';self.links=[];self.alternates={};self.text=[];self.schema=[]
        self._title=False;self._h1=False;self._skip=0;self._link=None;self._schema=None
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='html':self.lang=a.get('lang','')
        if tag=='title':self._title=True
        if tag=='h1':self._h1=True;self.h1.append('')
        if tag in ('script','style'):
            self._skip+=1
            if tag=='script' and a.get('type')=='application/ld+json':self._schema=''
        if tag=='meta':
            key=a.get('name','').lower()
            if key=='description':self.description=a.get('content','')
            if key in ('robots','googlebot'):self.robots+=' '+a.get('content','')
        if tag=='link':
            if a.get('rel')=='canonical':self.canonical=urljoin(self.url,a.get('href',''))
            if a.get('hreflang'):self.alternates[a['hreflang']]=urljoin(self.url,a.get('href',''))
        if tag=='a' and a.get('href'):
            self._link={'url':normalize_url(urljoin(self.url,a['href'])),'anchor':'','rel':a.get('rel','').split()};self.links.append(self._link)
    def handle_data(self,data):
        if self._schema is not None:self._schema+=data
        if self._skip:return
        if self._title:self.title+=data
        if self._h1:self.h1[-1]+=data
        if self._link is not None:self._link['anchor']+=data
        if data.strip():self.text.append(data.strip())
    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self._skip=max(0,self._skip-1)
            if self._schema is not None:
                try:self.schema.append(json.loads(self._schema))
                except ValueError:self.schema.append({'error':'invalid JSON-LD'})
                self._schema=None
        if tag=='title':self._title=False
        if tag=='h1':self._h1=False
        if tag=='a':self._link=None
    def document(self):
        return {k:getattr(self,k) for k in ('url','title','h1','lang','canonical','description','robots','links','alternates','schema','text')}

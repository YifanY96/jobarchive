"""职投档案 — localhost-only job archive. Python 3.12+, standard library only."""
from __future__ import annotations

import argparse
import base64
import csv
import ctypes
import hashlib
import html
import http.client
import io
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import sys
import threading
import time
import uuid
import webbrowser
import zipfile
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
STATUSES = ['待投递', '已投递', '初筛', '笔试', '面试', 'Offer', '已拒绝', '已撤回']
MAX_FILE = 25 * 1024 * 1024
MAX_BODY = 80 * 1024 * 1024
MAX_BACKUP = 400 * 1024 * 1024
TABLES = ('applications', 'documents', 'history', 'mails')
LOCK = threading.RLock()
NOW = lambda: datetime.now(timezone.utc).isoformat(timespec='seconds')
ID = lambda: str(uuid.uuid4())


def valid_id(value):
    try:
        return str(uuid.UUID(str(value))) == str(value)
    except (ValueError, TypeError, AttributeError):
        return False


def text(value, limit=200000):
    if not isinstance(value, str):
        raise ValueError('字段内容必须是文字')
    if len(value) > limit:
        raise ValueError('内容过长，请缩短后重试')
    return value.strip()


def valid_url(value):
    if not value:
        return ''
    u = urlsplit(text(value, 4000))
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        raise ValueError('请填写完整的 http:// 或 https:// 网页链接')
    return value


class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Archive:
    def __init__(self, directory):
        self.dir = Path(directory).resolve()
        self.files = self.dir / 'files'
        self.files.mkdir(parents=True, exist_ok=True)
        self.db = self.dir / 'archive.sqlite3'
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS applications(
              id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
              url TEXT NOT NULL, jd TEXT NOT NULL, applied_date TEXT NOT NULL,
              status TEXT NOT NULL, notes TEXT NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents(
              id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
              kind TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
              sha256 TEXT NOT NULL, submitted_date TEXT NOT NULL, label TEXT NOT NULL,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history(
              id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
              event TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mails(
              id TEXT PRIMARY KEY, account TEXT NOT NULL, gmail_id TEXT NOT NULL,
              thread_id TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL,
              received_at TEXT NOT NULL, snippet TEXT NOT NULL, body TEXT NOT NULL,
              application_id TEXT REFERENCES applications(id),
              UNIQUE(account,gmail_id));
            CREATE INDEX IF NOT EXISTS idx_app_status_date ON applications(status,applied_date);
            CREATE INDEX IF NOT EXISTS idx_doc_application ON documents(application_id);
            CREATE INDEX IF NOT EXISTS idx_history_application ON history(application_id,created_at);
            ''')

    def connect(self):
        c = sqlite3.connect(self.db, timeout=30, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def all(self, table):
        if table not in TABLES:
            raise ValueError('未知数据表')
        with self.connect() as c:
            return [dict(r) for r in c.execute(f'SELECT * FROM {table}')]

    def application(self, aid):
        with self.connect() as c:
            r = c.execute('SELECT * FROM applications WHERE id=?', (aid,)).fetchone()
            if not r:
                raise ValueError('没有找到这条投递记录')
            result = dict(r)
            result['documents'] = [dict(x) for x in c.execute(
                'SELECT * FROM documents WHERE application_id=? ORDER BY created_at DESC', (aid,))]
            result['history'] = [dict(x) for x in c.execute(
                'SELECT * FROM history WHERE application_id=? ORDER BY created_at DESC', (aid,))]
            result['mails'] = [dict(x) for x in c.execute(
                'SELECT * FROM mails WHERE application_id=? ORDER BY received_at DESC', (aid,))]
            return result

    def save(self, payload, aid=None):
        old = self.application(aid) if aid else None
        fields = {k: text(payload.get(k, ''), 200000 if k in ('jd','notes') else 4000)
                  for k in ('company', 'title', 'url', 'jd', 'applied_date', 'status', 'notes')}
        if not fields['company'] or not fields['title']:
            raise ValueError('公司和职位名称不能为空')
        valid_url(fields['url'])
        if fields['status'] not in STATUSES:
            raise ValueError('请选择有效的投递状态')
        if fields['applied_date']:
            date.fromisoformat(fields['applied_date'])
        aid = aid or ID()
        if not valid_id(aid):
            raise ValueError('记录编号无效')
        uploads = payload.get('uploads', [])
        if not isinstance(uploads, list) or len(uploads) > 10:
            raise ValueError('一次最多归档 10 个文件')
        prepared = []
        for u in uploads:
            name = text(u.get('name',''), 255)
            if not name or any(ch in name for ch in '\\/:\x00'):
                raise ValueError('附件名称不合法')
            if Path(name).suffix.lower() not in ('.pdf','.doc','.docx','.txt','.md','.rtf'):
                raise ValueError('附件支持 PDF、DOC、DOCX、TXT、MD、RTF')
            kind = u.get('kind')
            if kind not in ('cv','letter','other'):
                raise ValueError('附件类型无效')
            raw = base64.b64decode(u.get('data',''), validate=True)
            if not raw or len(raw) > MAX_FILE:
                raise ValueError('附件不能为空，单个文件最大 25 MB')
            submitted = text(u.get('submitted_date', fields['applied_date']), 20)
            if submitted:
                date.fromisoformat(submitted)
            prepared.append((ID(),kind,name,raw,submitted,text(u.get('label',''),200)))
        letter = text(payload.get('new_letter',''))
        if letter:
            letter_date=text(payload.get('submitted_date',fields['applied_date']),20)
            if letter_date: date.fromisoformat(letter_date)
            prepared.append((ID(),'letter','动机信_'+(fields['applied_date'] or date.today().isoformat())+'.txt',
                             letter.encode('utf-8'),letter_date,
                             text(payload.get('document_label','正文归档'),200)))
        written = []
        try:
            with LOCK, self.connect() as c:
                stamp = NOW()
                c.execute('''INSERT INTO applications VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET company=excluded.company,title=excluded.title,
                url=excluded.url,jd=excluded.jd,applied_date=excluded.applied_date,status=excluded.status,
                notes=excluded.notes,updated_at=excluded.updated_at''',
                (aid,*(fields[k] for k in ('company','title','url','jd','applied_date','status','notes')),
                 old['created_at'] if old else stamp,stamp))
                for did,kind,name,raw,submitted,label in prepared:
                    path = self.files / did
                    path.write_bytes(raw)
                    written.append(path)
                    c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',
                        (did,aid,kind,name,len(raw),hashlib.sha256(raw).hexdigest(),submitted,label,stamp))
                changed = [k for k in fields if old and old[k] != fields[k]]
                event = '创建投递记录' if not old else ('更新：'+ '、'.join(
                    {'company':'公司','title':'职位','url':'链接','jd':'JD','applied_date':'投递日期',
                     'status':'状态','notes':'备注'}[k] for k in changed) if changed else '保存记录')
                if prepared:
                    event += f'；归档 {len(prepared)} 份新材料'
                c.execute('INSERT INTO history VALUES(?,?,?,?,?)',
                    (ID(),aid,event,json.dumps(fields,ensure_ascii=False),stamp))
        except Exception:
            for p in written:
                p.unlink(missing_ok=True)
            raise
        return self.application(aid)

    def backup(self):
        with LOCK:
            manifest = {'format':'jobarchive','version':1,'created_at':NOW(),
                        'tables':{t:self.all(t) for t in TABLES}}
            buf = io.BytesIO()
            with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('records.json',json.dumps(manifest,ensure_ascii=False,indent=2))
                for doc in manifest['tables']['documents']:
                    path = self.files / doc['id']
                    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != doc['sha256']:
                        raise ValueError('有附件缺失或被修改，无法生成完整备份：'+doc['name'])
                    z.write(path,'files/'+doc['id'])
            return buf.getvalue()

    def restore(self, raw):
        if len(raw) > MAX_BACKUP:
            raise ValueError('备份最大 400 MB')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                infos = z.infolist()
                if len(infos) > 10000 or sum(x.file_size for x in infos) > MAX_BACKUP:
                    raise ValueError('备份解压大小或文件数量超出限制')
                names = [i.filename for i in infos]
                if len(names) != len(set(names)) or 'records.json' not in names:
                    raise ValueError('备份结构无效')
                if z.getinfo('records.json').file_size > 30*1024*1024:
                    raise ValueError('备份记录过大')
                manifest = json.loads(z.read('records.json'))
                if manifest.get('format') != 'jobarchive' or manifest.get('version') != 1:
                    raise ValueError('这不是职投档案的备份文件')
                tables = manifest['tables']
                if set(tables) != set(TABLES):
                    raise ValueError('备份缺少数据表')
                expected = {'records.json'}
                content = {}
                for table, rows in tables.items():
                    if not isinstance(rows,list) or len(rows)>10000:
                        raise ValueError('备份记录无效')
                    for row in rows:
                        if not valid_id(row.get('id')):
                            raise ValueError('备份记录编号不合法')
                for r in tables['applications']:
                    if r['status'] not in STATUSES:
                        raise ValueError('备份中的状态无效')
                    valid_url(r['url'])
                for d in tables['documents']:
                    name = 'files/'+d['id']
                    expected.add(name)
                    if z.getinfo(name).file_size > MAX_FILE:
                        raise ValueError('备份附件过大')
                    data = z.read(name)
                    if len(data)!=d['size'] or hashlib.sha256(data).hexdigest()!=d['sha256']:
                        raise ValueError('附件校验失败：'+d['name'])
                    content[d['id']] = data
                if set(names) != expected:
                    raise ValueError('备份包含非预期文件')
        except (zipfile.BadZipFile,KeyError,TypeError,json.JSONDecodeError) as exc:
            raise ValueError('备份文件损坏或格式不正确') from exc
        with LOCK:
            safety = self.dir / 'backups'
            safety.mkdir(exist_ok=True)
            backup_name = '恢复前_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+secrets.token_hex(3)+'.zip'
            (safety/backup_name).write_bytes(self.backup())
            stage = self.dir / ('restore-'+ID())
            previous = self.dir / ('previous-'+ID())
            stage.mkdir()
            swapped = False
            try:
                for did,data in content.items():
                    (stage/did).write_bytes(data)
                with self.connect() as c:
                    for t in reversed(TABLES):
                        c.execute(f'DELETE FROM {t}')
                    for t in TABLES:
                        columns = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
                        for row in tables[t]:
                            if set(row)!=set(columns):
                                raise ValueError('备份数据列不匹配')
                            c.execute(f'INSERT INTO {t} VALUES({",".join("?" for _ in columns)})',
                                      [row[k] for k in columns])
                    self.files.rename(previous)
                    stage.rename(self.files)
                    swapped = True
            except Exception:
                if swapped:
                    shutil.rmtree(self.files)
                    previous.rename(self.files)
                elif previous.exists():
                    previous.rename(self.files)
                raise
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
            shutil.rmtree(previous,ignore_errors=True)
        return {'safety_backup':backup_name,'count':len(tables['applications'])}


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.skip=0; self.jsonld=[]; self.script=None; self.title=[]; self.in_title=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script':
            self.script=[] if attrs.get('type','').lower()=='application/ld+json' else None
        if tag in ('script','style','noscript','svg','nav','footer','header'):
            self.skip+=1
        if tag=='title': self.in_title=True
        if tag in ('p','div','section','li','br','h1','h2','h3','article') and not self.skip:
            self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag=='script' and self.script is not None:
            self.jsonld.append(''.join(self.script)); self.script=None
        if tag in ('script','style','noscript','svg','nav','footer','header'):
            self.skip=max(0,self.skip-1)
        if tag=='title': self.in_title=False
        if tag in ('p','div','li','h1','h2','h3') and not self.skip: self.parts.append('\n')
    def handle_data(self,data):
        if self.script is not None: self.script.append(data)
        if self.in_title: self.title.append(data)
        if not self.skip: self.parts.append(data)
    def plain(self):
        return '\n'.join(x.strip() for x in ''.join(self.parts).splitlines() if x.strip())


def html_text(source):
    parser=PageText(); parser.feed(source); return parser.plain()


def extract_jd(source):
    p=PageText(); p.feed(source)
    def walk(obj):
        if isinstance(obj,dict):
            typ=obj.get('@type',[])
            if typ=='JobPosting' or (isinstance(typ,list) and 'JobPosting' in typ):
                yield obj
            for v in obj.values(): yield from walk(v)
        elif isinstance(obj,list):
            for v in obj: yield from walk(v)
    for raw in p.jsonld:
        try:
            jobs=list(walk(json.loads(raw)))
        except (ValueError,RecursionError):
            continue
        if jobs and jobs[0].get('description'):
            job=jobs[0]; org=job.get('hiringOrganization',{})
            return {'title':str(job.get('title','')),'company':str(org.get('name','')) if isinstance(org,dict) else '',
                    'jd':html_text(str(job['description'])),'method':'结构化职位信息（JobPosting）'}
    result=p.plain()
    if len(result)<80:
        raise ValueError('网页内容不足，可能需要登录或 JavaScript 渲染。请复制 JD 手动粘贴。')
    return {'title':''.join(p.title).strip(),'company':'','jd':result[:100000],
            'method':'网页正文；可能包含导航或其他内容，请核对后保存'}


def public_address(host,port):
    try:
        addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError('无法解析这个网站的地址') from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('只支持公开招聘网页，不读取本机或局域网地址')
    return addresses[0][4][0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,port,ip):
        super().__init__(host,port,timeout=15,context=ssl.create_default_context()); self.ip=ip
    def connect(self):
        self.sock=self._context.wrap_socket(socket.create_connection((self.ip,self.port),self.timeout),
                                           server_hostname=self.host)


def fetch_jd(url):
    valid_url(url)
    for _ in range(5):
        u=urlsplit(url)
        if u.port not in (None,80,443): raise ValueError('只支持标准 HTTP/HTTPS 网站端口')
        port=u.port or (443 if u.scheme=='https' else 80)
        ip=public_address(u.hostname,port)
        if u.scheme=='https':
            conn=PinnedHTTPS(u.hostname,port,ip)
        else:
            conn=http.client.HTTPConnection(ip,port,timeout=15)
        try:
            target=u.path or '/'
            if u.query: target+='?'+u.query
            conn.request('GET',target,headers={'Host':u.hostname,'User-Agent':'JobArchive/1.0 (+local job archive)',
                                              'Accept':'text/html,application/xhtml+xml','Accept-Encoding':'identity'})
            r=conn.getresponse()
            if r.status in (301,302,303,307,308):
                url=urljoin(url,r.getheader('Location','')); valid_url(url); continue
            if r.status!=200:
                raise ValueError(f'网站返回 HTTP {r.status}，请打开网页复制 JD 手动粘贴。')
            ctype=r.getheader('Content-Type','')
            if 'html' not in ctype.lower(): raise ValueError('这不是可读取的 HTML 职位网页')
            raw=r.read(4*1024*1024+1)
            if len(raw)>4*1024*1024: raise ValueError('网页过大，请手动复制 JD')
            charset=re.search(r'charset=["\']?([\w-]+)',ctype,re.I)
            encoding=charset.group(1) if charset else 'utf-8'
            try: source=raw.decode(encoding,errors='replace')
            except LookupError: source=raw.decode('utf-8',errors='replace')
            result=extract_jd(source); result.update(url=url,fetched_at=NOW()); return result
        finally:
            conn.close()
    raise ValueError('网页跳转过多，请手动粘贴 JD')


def protect(raw, decrypt=False):
    """Windows user-bound DPAPI; do not silently fall back to plaintext."""
    if os.name!='nt': raise ValueError('Gmail 凭据存储目前需要 Windows 用户加密服务')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('length',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buf=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte))); out=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p]; kernel.LocalFree.restype=ctypes.c_void_p
    if decrypt:
        fn=crypt.CryptUnprotectData
        fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,
                     ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    else:
        fn=crypt.CryptProtectData
        fn.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,
                     ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):
        raise ValueError('无法加密/读取 Gmail 凭据，请使用原 Windows 用户运行软件')
    try: return ctypes.string_at(out.data,out.length)
    finally: kernel.LocalFree(out.data)


def google_request(url, data=None, token=None):
    headers={'Accept':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    body=urlencode(data).encode() if data is not None else None
    req=Request(url,body,headers)
    try:
        with urlopen(req,timeout=25) as r: return json.loads(r.read(12*1024*1024))
    except HTTPError as exc:
        try: detail=json.loads(exc.read(20000))
        except ValueError: detail={}
        error=detail.get('error',{})
        msg=error.get('message','') if isinstance(error,dict) else detail.get('error_description',error)
        raise ValueError(f'Google 返回 HTTP {exc.code}：{str(msg)[:300]}。请检查授权和 Gmail API 配置。') from exc


def decode_gmail_body(payload):
    plain=[]; rich=[]
    def walk(p):
        if p.get('filename'): return
        raw=p.get('body',{}).get('data')
        if raw:
            try: s=base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)).decode('utf-8',errors='replace')
            except ValueError: s=''
            if p.get('mimeType')=='text/plain': plain.append(s)
            elif p.get('mimeType')=='text/html': rich.append(html_text(s))
        for child in p.get('parts',[]): walk(child)
    walk(payload)
    return '\n\n'.join(plain or rich)[:300000]


class Gmail:
    def __init__(self,store):
        self.store=store; self.path=store.dir/'gmail-credentials.dpapi'; self.pending={}
    def load(self):
        return json.loads(protect(self.path.read_bytes(),True)) if self.path.exists() else {}
    def write(self,value):
        data=protect(json.dumps(value).encode()); tmp=self.path.with_suffix('.tmp')
        tmp.write_bytes(data); tmp.replace(self.path)
    def status(self):
        v=self.load()
        return {'configured':bool(v.get('client_id')),'connected':bool(v.get('refresh_token') or v.get('access_token')),
                'email':v.get('email',''),'scope':'只读 Gmail','storage':'Windows 当前用户加密'}
    def configure(self,credentials):
        v=credentials.get('installed')
        if not isinstance(v,dict) or not str(v.get('client_id','')).endswith('.apps.googleusercontent.com'):
            raise ValueError('请导入 Google「桌面应用」类型的 OAuth 客户端 JSON 文件')
        with LOCK:
            self.write({'client_id':v['client_id'],'client_secret':v.get('client_secret','')})
            # Avoid accidentally displaying another previously connected account's inbox.
            with self.store.connect() as c: c.execute('DELETE FROM mails')
        return self.status()
    def authorize(self,origin):
        v=self.load()
        if not v.get('client_id'): raise ValueError('请先导入 Google OAuth 桌面客户端 JSON')
        verifier=secrets.token_urlsafe(64); state=secrets.token_urlsafe(32)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        redirect=origin+'/oauth/callback'
        self.pending={state:{'verifier':verifier,'redirect':redirect,'created':time.time()}}
        params={'client_id':v['client_id'],'redirect_uri':redirect,'response_type':'code',
                'scope':'https://www.googleapis.com/auth/gmail.readonly','access_type':'offline',
                'prompt':'consent','state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
        return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params)
    def callback(self,args):
        state=args.get('state',[''])[0]; pending=self.pending.pop(state,None)
        if not pending or time.time()-pending['created']>600: raise ValueError('授权链接已过期，请重新连接')
        if args.get('error'): raise ValueError('Google 授权未完成：'+args['error'][0])
        code=args.get('code',[''])[0]
        if not code: raise ValueError('没有收到 Google 授权码')
        v=self.load()
        result=google_request('https://oauth2.googleapis.com/token',{
            'code':code,'client_id':v['client_id'],'client_secret':v.get('client_secret',''),
            'redirect_uri':pending['redirect'],'grant_type':'authorization_code','code_verifier':pending['verifier']})
        v.update(result); v['expires_at']=time.time()+result.get('expires_in',3600)-60
        profile=google_request('https://gmail.googleapis.com/gmail/v1/users/me/profile',token=v['access_token'])
        v['email']=profile['emailAddress']; self.write(v)
    def token(self):
        v=self.load()
        if not v.get('access_token'): raise ValueError('请先登录并授权 Gmail')
        if time.time()>=v.get('expires_at',0):
            if not v.get('refresh_token'): raise ValueError('Gmail 登录已过期，请重新授权')
            result=google_request('https://oauth2.googleapis.com/token',{
                'client_id':v['client_id'],'client_secret':v.get('client_secret',''),
                'refresh_token':v['refresh_token'],'grant_type':'refresh_token'})
            v.update(result); v['expires_at']=time.time()+result.get('expires_in',3600)-60; self.write(v)
        return v['access_token'],v['email']
    def sync(self,query,page_token=''):
        query=text(query or 'newer_than:90d',2000)
        token,account=self.token()
        params={'q':query,'maxResults':30}
        if page_token: params['pageToken']=text(page_token,2000)
        page=google_request('https://gmail.googleapis.com/gmail/v1/users/me/messages?'+urlencode(params),token=token)
        count=0; errors=[]
        for stub in page.get('messages',[]):
            mid=stub.get('id','')
            if not re.fullmatch('[0-9a-fA-F]+',mid): continue
            try:
                message=google_request('https://gmail.googleapis.com/gmail/v1/users/me/messages/'+mid+'?format=full',token=token)
                payload=message.get('payload',{})
                headers={x['name'].lower():x['value'] for x in payload.get('headers',[])}
                received=datetime.fromtimestamp(int(message.get('internalDate','0'))/1000,timezone.utc).isoformat()
                with LOCK,self.store.connect() as c:
                    c.execute('''INSERT INTO mails VALUES(?,?,?,?,?,?,?,?,?,NULL)
                    ON CONFLICT(account,gmail_id) DO UPDATE SET sender=excluded.sender,subject=excluded.subject,
                    received_at=excluded.received_at,snippet=excluded.snippet,body=excluded.body''',
                    (ID(),account,mid,message.get('threadId',mid),headers.get('from',''),headers.get('subject','（无主题）'),
                     received,html.unescape(message.get('snippet','')),decode_gmail_body(payload)))
                count+=1
            except (ValueError,OSError) as exc: errors.append(str(exc))
        return {'count':count,'next_page':page.get('nextPageToken',''),'errors':errors[:3]}
    def disconnect(self):
        v=self.load()
        # Local disconnect is guaranteed even if network revocation fails.
        warning=''
        token=v.get('refresh_token') or v.get('access_token')
        if token:
            try:
                req=Request('https://oauth2.googleapis.com/revoke',urlencode({'token':token}).encode())
                with urlopen(req,timeout=10) as r: r.read()
            except (OSError,HTTPError): warning='本机已断开；网络撤销未完成，可在 Google 账号权限页撤销授权。'
        self.path.unlink(missing_ok=True)
        self.pending.clear()
        with LOCK,self.store.connect() as c: c.execute('DELETE FROM mails')
        return {'warning':warning}


class Handler(BaseHTTPRequestHandler):
    server_version='JobArchive/1.0'
    def log_message(self,fmt,*args):
        # Never log OAuth codes, credentials, personal filenames or content.
        pass
    def send_bytes(self,raw,ctype='application/json; charset=utf-8',code=200,extra=None):
        self.send_response(code)
        self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'")
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)
    def json(self,obj,code=200):
        self.send_bytes(json.dumps(obj,ensure_ascii=False).encode(),code=code)
    def guard(self,write=False):
        if self.headers.get('Host') != self.server.authority:
            raise PermissionError('仅允许本机访问，请使用软件提供的网址')
        origin=self.headers.get('Origin')
        if origin and origin != self.server.origin: raise PermissionError('拒绝跨站请求')
        if write or self.path.startswith('/api/'):
            if not secrets.compare_digest(self.headers.get('X-Archive-Token',''),self.server.token):
                raise PermissionError('请刷新软件页面后重试')
    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<=0 or size>MAX_BODY: raise ValueError('请求为空或过大')
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            raise ValueError('请求格式无效')
        result=json.loads(self.rfile.read(size))
        if not isinstance(result,dict): raise ValueError('请求格式无效')
        return result
    def do_GET(self):
        try:
            self.guard()
            path=urlsplit(self.path).path; args=parse_qs(urlsplit(self.path).query)
            store=self.server.store
            if path=='/oauth/callback':
                self.server.gmail.callback(args)
                self.send_bytes('<!doctype html><meta charset="utf-8"><title>Gmail 已连接</title><p>Gmail 已连接。可以关闭此页，回到职投档案刷新邮箱状态。</p>'.encode(),'text/html; charset=utf-8'); return
            if path=='/api/session': self.json({'token':self.server.token,'statuses':STATUSES}); return
            if path=='/api/applications': self.json(store.all('applications')); return
            if path.startswith('/api/applications/'):
                self.json(store.application(path.rsplit('/',1)[1])); return
            if path=='/api/mails': self.json(sorted(store.all('mails'),key=lambda x:x['received_at'],reverse=True)); return
            if path=='/api/gmail': self.json(self.server.gmail.status()); return
            if path=='/api/info':
                self.json({'data_dir':str(store.dir),'version':'1.1.0','desktop':getattr(self.server,'desktop',False),'gmail':self.server.gmail.status()}); return
            if path=='/api/backup':
                self.send_bytes(store.backup(),'application/zip',extra={'Content-Disposition':
                    'attachment; filename="JobArchive-'+date.today().isoformat()+'.zip"'}); return
            if path=='/api/csv':
                out=io.StringIO(newline=''); w=csv.writer(out)
                fields=['company','title','url','applied_date','status','notes','jd']
                w.writerow(['公司','职位','投递网页','投递日期','状态','备注','职位描述'])
                for row in store.all('applications'):
                    w.writerow([("'"+str(row[k]) if str(row[k]).lstrip().startswith(('=','+','-','@')) else row[k]) for k in fields])
                self.send_bytes(out.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8',extra={
                    'Content-Disposition':'attachment; filename="applications.csv"'}); return
            if path.startswith('/files/'):
                did=path.rsplit('/',1)[1]
                if not valid_id(did): raise ValueError('附件编号无效')
                with store.connect() as c: r=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
                if not r: raise ValueError('没有找到附件')
                raw=(store.files/did).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=r['sha256']: raise ValueError('附件校验失败，请使用备份恢复')
                self.send_bytes(raw,'application/octet-stream',extra={
                    'Content-Disposition':"attachment; filename*=UTF-8''"+quote(r['name'],safe='')}); return
            assets={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/favicon.svg':'favicon.svg'}
            if path not in assets: self.json({'error':'页面不存在'},404); return
            asset=ROOT/'web'/assets[path]
            raw=asset.read_bytes()
            if path=='/': raw=raw.replace(b'__ARCHIVE_TOKEN__',self.server.token.encode())
            self.send_bytes(raw,mimetypes.guess_type(str(asset))[0]+('; charset=utf-8' if path!='favicon.svg' else ''))
        except PermissionError as exc: self.json({'error':str(exc)},403)
        except (ValueError,KeyError,OSError,sqlite3.Error) as exc:
            if urlsplit(self.path).path=='/oauth/callback':
                self.send_bytes(('<!doctype html><meta charset="utf-8"><p>授权未完成：'+html.escape(str(exc))+'</p><p>回到职投档案重新连接。</p>').encode(),'text/html; charset=utf-8',400)
            else: self.json({'error':str(exc)},400)
    def do_POST(self):
        try:
            self.guard(True); path=urlsplit(self.path).path; store=self.server.store
            if path=='/api/restore' and self.headers.get('Content-Type')=='application/zip':
                size=int(self.headers.get('Content-Length','0'))
                if self.headers.get('X-Confirm')!='RESTORE' or size<=0 or size>MAX_BACKUP:
                    raise ValueError('请确认恢复，备份上限为 400 MB')
                self.json(store.restore(self.rfile.read(size))); return
            p=self.body()
            if path=='/api/shutdown':
                self.json({'ok':True})
                threading.Thread(target=self.server.shutdown,daemon=True).start(); return
            if path=='/api/applications': self.json(store.save(p)); return
            if path.startswith('/api/applications/'):
                self.json(store.save(p,path.rsplit('/',1)[1])); return
            if path=='/api/fetch-jd': self.json(fetch_jd(text(p.get('url',''),4000))); return
            if path=='/api/restore':
                if p.get('confirm')!='RESTORE': raise ValueError('恢复会替换当前档案，请先确认')
                self.json(store.restore(base64.b64decode(p.get('data',''),validate=True))); return
            if path=='/api/gmail/configure': self.json(self.server.gmail.configure(p)); return
            if path=='/api/gmail/connect': self.json({'url':self.server.gmail.authorize(self.server.origin)}); return
            if path=='/api/gmail/sync': self.json(self.server.gmail.sync(p.get('query',''),p.get('page_token',''))); return
            if path=='/api/gmail/disconnect': self.json(self.server.gmail.disconnect()); return
            if path=='/api/mails/link':
                mid=p.get('id'); aid=p.get('application_id') or None
                if aid: store.application(aid)
                with LOCK,store.connect() as c:
                    result=c.execute('UPDATE mails SET application_id=? WHERE id=?',(aid,mid))
                    if result.rowcount!=1: raise ValueError('没有找到邮件')
                self.json({'ok':True}); return
            self.json({'error':'接口不存在'},404)
        except PermissionError as exc: self.json({'error':str(exc)},403)
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,http.client.HTTPException) as exc:
            self.json({'error':str(exc)},400)


def make_server(data_dir,port=0):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    server.authority='127.0.0.1:'+str(server.server_port)
    server.origin='http://'+server.authority
    server.token=secrets.token_urlsafe(32)
    server.store=Archive(data_dir); server.gmail=Gmail(server.store)
    return server


def main():
    parser=argparse.ArgumentParser(description='职投档案 — 本地求职管理')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--data-dir',default=str(ROOT/'data'))
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    # Reuse an existing app only after verifying its data directory and version.
    active=Path(args.data_dir)/'running.json'
    if active.exists():
        try:
            prior=json.loads(active.read_text())
            parsed=urlsplit(prior['url'])
            if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path:
                raise ValueError('无效的运行地址')
            req=Request(prior['url']+'/api/info',headers={'X-Archive-Token':prior['token']})
            with urlopen(req,timeout=2) as r: info=json.loads(r.read())
            if info['data_dir']==str(Path(args.data_dir).resolve()):
                if args.open: webbrowser.open(prior['url'])
                print('职投档案已经运行：'+prior['url']); return
        except (ValueError,KeyError,OSError): pass
    server=make_server(args.data_dir,args.port)
    active.write_text(json.dumps({'url':server.origin,'token':server.token}),encoding='utf-8')
    print('职投档案：'+server.origin,flush=True)
    print('数据保存在：'+str(server.store.dir),flush=True)
    if args.open: webbrowser.open(server.origin)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        try:
            if json.loads(active.read_text(encoding='utf-8')).get('token')==server.token:
                active.unlink(missing_ok=True)
        except (OSError,ValueError): pass


if __name__=='__main__': main()

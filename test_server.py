import base64,io,json,tempfile,threading,unittest,zipfile
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import server as s
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=s.Archive(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def payload(self):return dict(company='测试公司',title='开发岗',url='https://example.com/job',jd='原始 JD',applied_date='2026-10-03',status='已投递',notes='')
    def test_immutable_documents_history_restore(self):
        p=self.payload();p['uploads']=[dict(name='CV.txt',kind='cv',data=base64.b64encode(b'CV version 1').decode())];p['new_letter']='实际提交动机信'
        a=self.store.save(p);did=a['documents'][0]['id'];original=(self.store.files/did).read_bytes();backup=self.store.backup()
        p['status']='面试';p['uploads'][0]['data']=base64.b64encode(b'CV version 2').decode();p['new_letter']=''
        updated=self.store.save(p,a['id']);self.assertEqual(len(updated['documents']),3);self.assertEqual((self.store.files/did).read_bytes(),original);self.assertEqual(len(updated['history']),2)
        r=self.store.restore(backup);restored=self.store.application(a['id']);self.assertEqual(restored['status'],'已投递');self.assertEqual(len(restored['documents']),2);self.assertTrue((self.store.dir/'backups'/r['safety_backup']).exists())
    def test_bad_backup_keeps_data(self):
        a=self.store.save(self.payload());out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('records.json',json.dumps({'format':'jobarchive','version':1,'tables':{t:self.store.all(t) for t in s.TABLES}}));z.writestr('../outside','bad')
        with self.assertRaises(ValueError):self.store.restore(out.getvalue())
        self.assertEqual(self.store.application(a['id'])['company'],'测试公司')
    def test_jd_and_private_urls(self):
        p=s.extract_jd('<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Analyst','hiringOrganization':{'name':'Acme'},'description':'<p>Analyze data</p>'})+'</script>')
        self.assertEqual(p['company'],'Acme');self.assertEqual(p['jd'],'Analyze data')
        for u in ['http://127.0.0.1','http://169.254.169.254','file:///etc/passwd']:
            with self.assertRaises(ValueError):s.fetch_jd(u)
    def test_email_and_dpapi(self):
        self.assertEqual(s.decode_gmail_body({'mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode('面试邀请'.encode()).decode()}}),'面试邀请')
        raw=b'private-test-token';enc=s.protect(raw);self.assertNotIn(raw,enc);self.assertEqual(s.protect(enc,True),raw)
    def test_api_guards_and_raw_restore(self):
        http=s.make_server(self.tmp.name);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            with self.assertRaises(HTTPError) as e:urlopen(http.origin+'/api/applications')
            self.assertEqual(e.exception.code,403)
            headers={'X-Archive-Token':http.token,'Content-Type':'application/json'}
            req=Request(http.origin+'/api/applications',json.dumps(self.payload()).encode(),headers)
            with urlopen(req) as r:a=json.load(r)
            req=Request(http.origin+'/api/applications',headers={**headers,'Origin':'https://evil.example'})
            with self.assertRaises(HTTPError):urlopen(req)
            backup=http.store.backup();req=Request(http.origin+'/api/restore',backup,{'X-Archive-Token':http.token,'X-Confirm':'RESTORE','Content-Type':'application/zip'})
            with urlopen(req) as r:self.assertEqual(json.load(r)['count'],1)
            with urlopen(http.origin) as r:self.assertIn(http.token,r.read().decode())
        finally:http.shutdown();http.server_close();thread.join()
    def test_gmail_oauth_and_sync_simulated(self):
        gmail=s.Gmail(self.store)
        gmail.configure({'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'test'}})
        params=parse_qs(urlsplit(gmail.authorize('http://127.0.0.1:12345')).query)
        self.assertEqual(params['code_challenge_method'],['S256']);self.assertEqual(params['scope'],['https://www.googleapis.com/auth/gmail.readonly'])
        with self.assertRaises(ValueError):gmail.callback({'state':['wrong'],'code':['code']})
        with patch.object(s,'google_request',side_effect=[{'access_token':'access','refresh_token':'refresh','expires_in':3600},{'emailAddress':'test@example.com'}]):
            gmail.callback({'state':params['state'],'code':['code']})
        self.assertTrue(gmail.status()['connected'])
        message={'id':'abcd','threadId':'ffff','internalDate':'1700000000000','snippet':'invite','payload':{'mimeType':'text/plain','headers':[{'name':'From','value':'jobs@example.com'},{'name':'Subject','value':'Interview'}],'body':{'data':base64.urlsafe_b64encode(b'Please join interview').decode()}}}
        with patch.object(s,'google_request',side_effect=[{'messages':[{'id':'abcd'}],'nextPageToken':'next'},message]):
            result=gmail.sync('subject:Interview')
        self.assertEqual(result['count'],1);self.assertEqual(result['next_page'],'next');self.assertEqual(self.store.all('mails')[0]['body'],'Please join interview')
        self.assertNotIn(b'access',self.store.backup())

if __name__=='__main__':unittest.main(verbosity=2)

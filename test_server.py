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
    def test_delete_keeps_other_records_and_mail_and_can_restore(self):
        p=self.payload();p['uploads']=[dict(name='CV.txt',kind='cv',data=base64.b64encode(b'submitted CV').decode())]
        a=self.store.save(p);did=a['documents'][0]['id']
        other=self.store.save({**self.payload(),'company':'Keep this company'})
        mid=s.ID()
        with self.store.connect() as c:
            c.execute('INSERT INTO mails VALUES(?,?,?,?,?,?,?,?,?,?)',(mid,'test@example.com','mail1','thread1','jobs@example.com','Interview',s.NOW(),'snippet','Original email',a['id']))
        result=self.store.delete_application(a['id'])
        self.assertTrue(result['ok']);self.assertEqual(self.store.application(other['id'])['company'],'Keep this company')
        with self.assertRaises(ValueError):self.store.application(a['id'])
        self.assertFalse((self.store.files/did).exists())
        self.assertEqual(self.store.all('documents'),[]);self.assertEqual(len(self.store.all('history')),1)
        mail=self.store.all('mails')[0];self.assertIsNone(mail['application_id']);self.assertEqual(mail['body'],'Original email')
        backup=self.store.dir/'backups'/result['safety_backup']
        self.store.restore(backup.read_bytes())
        self.assertEqual(self.store.application(a['id'])['documents'][0]['id'],did)
        self.assertEqual((self.store.files/did).read_bytes(),b'submitted CV')
        self.assertEqual(self.store.all('mails')[0]['application_id'],a['id'])
    def test_delete_backup_failure_keeps_records_and_files(self):
        p=self.payload();p['new_letter']='Keep this cover letter';a=self.store.save(p);did=a['documents'][0]['id']
        with patch.object(self.store,'backup',side_effect=OSError('Backup failed')):
            with self.assertRaises(OSError):self.store.delete_application(a['id'])
        with patch.object(s.Path,'write_bytes',side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):self.store.delete_application(a['id'])
        self.assertEqual(self.store.application(a['id'])['company'],a['company'])
        self.assertEqual((self.store.files/did).read_text(encoding='utf-8'),'Keep this cover letter')
    def test_delete_api_requires_token_and_explicit_confirmation(self):
        a=self.store.save(self.payload());http=s.make_server(self.tmp.name)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        endpoint=http.origin+'/api/applications/'+a['id']+'/delete'
        def post(payload,token=None):
            headers={'Content-Type':'application/json'}
            if token:headers['X-Archive-Token']=token
            return urlopen(Request(endpoint,json.dumps(payload).encode(),headers))
        try:
            with self.assertRaises(HTTPError) as err:post({'confirm':'DELETE'})
            self.assertEqual(err.exception.code,403)
            with self.assertRaises(HTTPError) as err:post({},http.token)
            self.assertEqual(err.exception.code,400)
            self.assertEqual(self.store.application(a['id'])['status'],'已投递')
            with post({'confirm':'DELETE'},http.token) as response:self.assertTrue(json.load(response)['ok'])
            with self.assertRaises(ValueError):self.store.application(a['id'])
        finally:http.shutdown();http.server_close();thread.join()
    def test_racing_edit_does_not_recreate_deleted_record(self):
        p=self.payload();a=self.store.save(p);read=self.store.application;deleted=False
        def racing_read(aid):
            nonlocal deleted
            snapshot=read(aid)
            if not deleted:
                deleted=True;self.store.delete_application(aid)
            return snapshot
        with patch.object(self.store,'application',side_effect=racing_read):
            with self.assertRaisesRegex(ValueError,'已删除'):self.store.save(p,a['id'])
        self.assertEqual(self.store.all('applications'),[])
    def test_preferences_survive_reopening_without_changing_records(self):
        a=self.store.save(self.payload()); before=self.store.all('applications')
        self.assertEqual(self.store.preferences(),{'language':'zh-CN'})
        self.store.save_preferences({'language':'en'})
        reopened=s.Archive(self.tmp.name)
        self.assertEqual(reopened.preferences(),{'language':'en'})
        self.assertEqual(reopened.all('applications'),before)
        with self.assertRaises(ValueError):reopened.save_preferences({'language':'unsupported'})
        self.assertEqual(reopened.preferences(),{'language':'en'})
        reopened.restore(reopened.backup())
        self.assertEqual(reopened.preferences(),{'language':'en'})
    def test_quick_status_preserves_documents_and_fields(self):
        p=self.payload();p['new_letter']='Original letter';a=self.store.save(p)
        original=self.store.application(a['id'])
        updated=self.store.update_status(a['id'],'面试')
        self.assertEqual(updated['status'],'面试')
        for field in ('company','title','jd','notes','url','applied_date','documents'):
            self.assertEqual(updated[field],original[field])
        self.assertEqual(len(updated['history']),2)
        self.assertEqual(len(self.store.update_status(a['id'],'面试')['history']),2)
        with self.assertRaises(ValueError):self.store.update_status(a['id'],'Interview')
        self.assertEqual(self.store.application(a['id'])['status'],'面试')
    def test_localized_http_csv_and_status_endpoint(self):
        http=s.make_server(self.tmp.name);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        headers={'X-Archive-Token':http.token,'Content-Type':'application/json'}
        def post(path,payload):
            with urlopen(Request(http.origin+path,json.dumps(payload).encode(),headers)) as response:return json.load(response)
        try:
            p=self.payload();p['notes']='=not a formula';a=post('/api/applications',p)
            post('/api/preferences',{'language':'en'})
            updated=post('/api/applications/'+a['id']+'/status',{'status':'面试'})
            self.assertEqual(updated['jd'],'原始 JD')
            with urlopen(Request(http.origin+'/api/csv',headers=headers)) as response:csv=response.read().decode('utf-8-sig')
            self.assertIn('Company,Job title,Application URL',csv);self.assertIn('Interview',csv)
            self.assertIn("'=not a formula",csv);self.assertIn('原始 JD',csv)
            with self.assertRaises(HTTPError) as error:post('/api/applications',{})
            self.assertEqual(json.load(error.exception)['error'],'Company and job title are required')
            with self.assertRaises(HTTPError):
                urlopen(Request(http.origin+'/api/preferences',b'{"language":"zh-CN"}',{'Content-Type':'application/json'}))
            self.assertEqual(http.store.preferences()['language'],'en')
            with urlopen(Request(http.origin+'/api/info',headers=headers)) as response:self.assertEqual(json.load(response)['language'],'en')
        finally:http.shutdown();http.server_close();thread.join()
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

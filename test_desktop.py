import io,json,tempfile,threading,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock
import desktop,server

class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.http=server.make_server(Path(self.tmp.name)/'data')
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.api=desktop.DesktopAPI(self.http);self.window=Mock();self.window.get_current_url.return_value=self.http.origin+'/'
        self.window.localization={}
        self.api._window=self.window;self.path=Path(self.tmp.name)/'export.zip';self.window.create_file_dialog.return_value=[str(self.path)]
    def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.tmp.cleanup()
    def test_backup_native_save_and_cancel(self):
        r=self.api.export(self.http.token,'backup');self.assertEqual(r['path'],str(self.path))
        with zipfile.ZipFile(self.path) as z:self.assertEqual(json.loads(z.read('records.json'))['format'],'jobarchive')
        self.window.create_file_dialog.return_value=None;self.assertTrue(self.api.export(self.http.token,'backup')['cancelled'])
    def test_export_rejects_wrong_token_and_external_page(self):
        self.assertIn('error',self.api.export('wrong','backup'));self.window.create_file_dialog.assert_not_called()
        self.window.get_current_url.return_value='https://example.com/';self.assertIn('error',self.api.export(self.http.token,'backup'));self.window.create_file_dialog.assert_not_called()
    def test_native_csv(self):
        r=self.api.export(self.http.token,'csv');self.assertIn('path',r);self.assertTrue(self.path.read_bytes().startswith(b'\xef\xbb\xbf'));self.assertIn('公司',self.path.read_text(encoding='utf-8-sig'))
    def test_english_native_export_and_window_title(self):
        self.http.store.save_preferences({'language':'en'})
        self.assertEqual(self.api.set_language(self.http.token),{'ok':True})
        self.window.set_title.assert_called_once_with('JobArchive')
        self.api.export(self.http.token,'csv')
        self.assertIn('Company',self.path.read_text(encoding='utf-8-sig'))
        self.assertTrue(self.window.create_file_dialog.call_args.kwargs['save_filename'].startswith('applications_'))
        self.assertIn('error',self.api.set_language('wrong'))
        self.window.get_current_url.return_value='https://example.com/'
        self.assertIn('error',self.api.set_language(self.http.token))
    def test_rejects_arbitrary_paths(self):
        self.assertIn('error',self.api.export(self.http.token,'document','../../secret'));self.assertIn('error',self.api.export(self.http.token,'unknown'));self.window.create_file_dialog.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)

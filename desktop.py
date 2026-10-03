"""Windows desktop entry point. No external Python installation is required when frozen."""
from __future__ import annotations
import argparse,ctypes,hashlib,json,logging,os,secrets,sys,threading,traceback
from datetime import date
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
import server

TITLE='职投档案'

class DesktopAPI:
    def __init__(self,http):
        self._http=http; self._window=None
    def export(self,token,kind,document_id=''):
        import webview
        try:
            if not isinstance(token,str) or not secrets.compare_digest(token,self._http.token):
                raise ValueError('请重新打开应用')
            if self._window.get_current_url()!=self._http.origin+'/':
                raise ValueError('当前页面不允许导出')
            if kind=='backup':
                raw=self._http.store.backup(); name='职投档案_'+date.today().isoformat()+'.zip'; extension='zip'
            elif kind=='csv':
                req=Request(self._http.origin+'/api/csv',headers={'X-Archive-Token':token})
                with urlopen(req,timeout=30) as response: raw=response.read()
                name='投递记录_'+date.today().isoformat()+'.csv'; extension='csv'
            elif kind=='document' and server.valid_id(document_id):
                with self._http.store.connect() as c:
                    d=c.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
                if not d: raise ValueError('附件不存在')
                raw=(self._http.store.files/document_id).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=d['sha256']: raise ValueError('附件校验失败')
                name=d['name']; extension=Path(name).suffix.lstrip('.')
            else: raise ValueError('无效的导出请求')
            result=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=name,
                file_types=(f'{extension.upper()} 文件 (*.{extension})','所有文件 (*.*)'))
            if not result: return {'cancelled':True}
            destination=Path(result[0])
            # Native dialog owns destination selection and overwrite confirmation.
            destination.write_bytes(raw)
            return {'path':str(destination)}
        except Exception as exc:
            return {'error':str(exc)}


def claim_instance(data_dir):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    key=hashlib.sha256(str(data_dir).lower().encode()).hexdigest()[:24]
    handle=kernel.CreateMutexW(None,False,'Local\\JobArchive-'+key)
    if not handle: raise OSError('无法创建应用实例')
    if ctypes.get_last_error()==183:
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p];user.FindWindowW.restype=ctypes.c_void_p
        user.ShowWindow.argtypes=[ctypes.c_void_p,ctypes.c_int]
        user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
        window=user.FindWindowW(None,TITLE)
        if window: user.ShowWindow(window,9);user.SetForegroundWindow(window)
        kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(handle)
        return None
    return handle


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir');parser.add_argument('--smoke-test',action='store_true')
    args=parser.parse_args()
    app_dir=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    data_dir=Path(args.data_dir).resolve() if args.data_dir else app_dir/'data'
    data_dir.mkdir(parents=True,exist_ok=True)
    # Windowed executables have no console; preserve a local diagnostic log.
    log=(data_dir/'desktop.log').open('a',encoding='utf-8')
    if sys.stdout is None: sys.stdout=log
    if sys.stderr is None: sys.stderr=log
    handle=None;http=None;window=None;thread=None
    active=data_dir/'running.json';status=data_dir/'desktop-status.json'
    try:
        handle=claim_instance(data_dir)
        if not handle: return
        # Move the existing browser instance to this app, preserving its data.
        if active.exists():
            try:
                prior=json.loads(active.read_text(encoding='utf-8'));u=urlsplit(prior['url'])
                if u.scheme=='http' and u.hostname=='127.0.0.1' and u.port and not u.path:
                    headers={'X-Archive-Token':prior['token']}
                    with urlopen(Request(prior['url']+'/api/info',headers=headers),timeout=2) as r: info=json.load(r)
                    if info.get('data_dir')==str(data_dir):
                        headers['Content-Type']='application/json'
                        with urlopen(Request(prior['url']+'/api/shutdown',b'{}',headers),timeout=3) as r:r.read()
            except (OSError,ValueError,KeyError): pass
        import webview
        webview.settings['ALLOW_DOWNLOADS']=True
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=True
        http=server.make_server(data_dir);http.desktop=True
        api=DesktopAPI(http)
        window=webview.create_window(TITLE,http.origin+'/',js_api=api,width=1280,height=860,
            min_size=(850,620),background_color='#f6f5f0',text_select=True)
        api._window=window
        active.write_text(json.dumps({'url':http.origin,'token':http.token}),encoding='utf-8')
        def serve():
            http.serve_forever()
            try: window.destroy()
            except Exception: pass
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        def loaded():
            status.write_text(json.dumps({'pid':os.getpid(),'url':http.origin,'ready':True,'renderer':'edgechromium'},ensure_ascii=False),encoding='utf-8')
            if args.smoke_test:
                try:
                    page=window.evaluate_js("({title:document.title,heading:document.getElementById('page-title').textContent,bridge:typeof window.pywebview.api.export==='function',token:!!document.querySelector('meta[name=archive-token]').content})")
                    req=Request(http.origin+'/api/info',headers={'X-Archive-Token':http.token})
                    with urlopen(req,timeout=5) as r:info=json.load(r)
                    (data_dir/'smoke-result.json').write_text(json.dumps({'ok':page['heading']=='投递档案' and page['bridge'] and page['token'] and info['desktop'],'page':page,'version':info['version']},ensure_ascii=False),encoding='utf-8')
                except Exception as exc:
                    (data_dir/'smoke-result.json').write_text(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),encoding='utf-8')
                finally:window.destroy()
        window.events.loaded+=loaded
        # Edge WebView2 is already installed on this computer; no admin installation.
        webview.start(gui='edgechromium',debug=False,private_mode=False,storage_path=str(data_dir/'webview'),
            localization={'global.quitConfirmation':'确定关闭职投档案？','global.cancel':'取消','global.saveFile':'保存文件','global.openFile':'打开文件'})
    except Exception:
        traceback.print_exc(file=log);log.flush()
        ctypes.windll.user32.MessageBoxW(None,'应用未能启动。请查看 data/desktop.log。\n需要 Microsoft Edge WebView2 Runtime。',TITLE,16)
        if args.smoke_test: raise
    finally:
        if http:
            if thread and thread.is_alive(): http.shutdown()
            http.server_close()
            if thread:thread.join(timeout=3)
            try:
                if json.loads(active.read_text(encoding='utf-8')).get('token')==http.token:
                    active.unlink(missing_ok=True)
            except (OSError,ValueError):pass
            status.unlink(missing_ok=True)
        if handle:
            kernel=ctypes.WinDLL('kernel32');kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(handle)
        log.close()

if __name__=='__main__':main()

"""Run with a build environment containing pywebview, PyInstaller and Pillow."""
import argparse,subprocess,sys
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description='Build the JobArchive Windows desktop application')
parser.add_argument('--output-dir',type=Path,default=root/'build')
args=parser.parse_args()
work=args.output_dir.resolve()
work.mkdir(parents=True,exist_ok=True)
icon=Image.new('RGBA',(256,256),(0,0,0,0));d=ImageDraw.Draw(icon)
d.rounded_rectangle((0,0,255,255),radius=52,fill='#244e42')
d.rounded_rectangle((72,57,184,207),radius=9,fill='#f2eddf')
for y,end in [(102,162),(132,162),(162,140)]:d.line((94,y,end,y),fill='#244e42',width=10)
icon.save(root/'app.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed',
    '--name','JobArchive','--icon',str(root/'app.ico'),'--add-data',str(root/'web')+';web',
    '--collect-all','webview','--collect-all','clr_loader','--collect-all','pythonnet',
    '--distpath',str(work/'dist'),'--workpath',str(work/'build'),'--specpath',str(work),
    str(root/'desktop.py')],check=True)

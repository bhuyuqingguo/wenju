"""Unprivileged paths and optional conservative rendering, shared by both platforms."""
import os,sys,tempfile
from pathlib import Path

def writable(path):
 try:
  path.mkdir(parents=True,exist_ok=True)
  with tempfile.TemporaryFile(dir=path):pass
  return True
 except OSError:return False

def data_directory(root):
 explicit=os.environ.get('WENJU_DATA_DIR')
 if explicit:
  path=Path(explicit)
  if not writable(path):raise OSError('指定工作数据目录不可写：'+str(path))
  return path
 portable=Path(root)/'工作数据'
 if writable(portable):return portable
 base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local'))) if sys.platform=='win32' else Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))
 path=base/'WenJu'
 if not writable(path):raise OSError('无法写入用户数据目录：'+str(path))
 return path

def configure_rendering():
 if '--safe-render' in sys.argv or os.environ.get('WENJU_LOW_POWER')=='1':
  os.environ.setdefault('QT_QUICK_BACKEND','software')
  os.environ['WENJU_LOW_POWER']='1'

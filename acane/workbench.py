"""Local import, environment preparation, and serial GPU job queue."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from .library import Library, now
from .media import digest

MODEL = 'model_bs_roformer_ep_317_sdr_12.9755.ckpt'
PARAMS = dict(segment_size=256, override_model_segment_size=True, overlap=2, batch_size=1)
MODEL_SHA = '5b84f37e8d444c8cb30c79d77f613a41c05868ff9c9ac6c7049c00aefae115aa'
CONFIG_SHA = '2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f'


def tail(path, limit=6000):
    try:
        with Path(path).open('rb') as stream:
            stream.seek(max(0, os.fstat(stream.fileno()).st_size-limit))
            return stream.read().decode('utf-8',errors='replace')
    except OSError:
        return ''


class Workbench:
    def __init__(self, root, backend_python=None, app_root=None):
        self.root = Path(root).resolve()
        self.app_root = Path(app_root or Path(__file__).resolve().parents[1])
        candidate = self.app_root / '.venv-separation' / ('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        self.python = str(backend_python or (candidate if candidate.exists() else sys.executable))
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='acane-separation')
        self.lock = threading.RLock()
        self.tasks = []
        self.environment = {'status':'unchecked','ready':False,'message':'点击“检查环境”确认分离组件。'}
        self.setup_log = None

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def import_upload(self, source, filename):
        with Library(self.root) as library:
            note = '界面上传：' + filename
            result = library.import_one(Path(source), source_note=note)
            with library.db:
                if result['status']=='imported':
                    library.db.execute('UPDATE assets SET filename=? WHERE id=?',(filename,result['id']))
                library.db.execute('DELETE FROM sources WHERE asset_id=? AND path=?',(result['id'],str(Path(source).resolve())))
                library.db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?)',
                    (result['id'],'upload:'+filename,note,now()))
            return {'id':result['id'],'status':result['status'],'filename':filename}

    def _model_files(self):
        target = self.root/'models'
        target.mkdir(exist_ok=True)
        for name in (MODEL, MODEL.replace('.ckpt','.yaml'), 'download_checks.json','mdx_model_data.json','vr_model_data.json'):
            source = self.app_root/'models'/name
            output = target/name
            if not output.exists() and source.is_file():
                try: os.link(source,output)
                except OSError: shutil.copyfile(source,output)
        return (target/MODEL).is_file() and (target/MODEL.replace('.ckpt','.yaml')).is_file()

    def check_environment(self):
        with self.lock:
            if self.environment['status'] in ('checking','installing'):
                return dict(self.environment)
            self.environment={'status':'checking','ready':False,'message':'正在检查运行环境…'}
            self.executor.submit(self._probe)
            return dict(self.environment)

    def _probe(self):
        script = '''import json,importlib.util
r={"backend":False,"cuda":False}
try:
 import torch
 from audio_separator.separator import Separator
 r.update(backend=True,cuda=torch.cuda.is_available(),torch=torch.__version__)
 if r['cuda']: r['device']=torch.cuda.get_device_name(0)
except Exception as e:r['error']=str(e)
print(json.dumps(r))'''
        try:
            process=subprocess.run([self.python,'-c',script],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
            if process.returncode:raise RuntimeError(process.stderr[-1500:] or 'Python 检查失败')
            data=json.loads(process.stdout.strip().splitlines()[-1])
            data.update(ffmpeg=bool(shutil.which('ffmpeg')),ffprobe=bool(shutil.which('ffprobe')),model=self._model_files())
            data['ready']=all(data[k] for k in ('backend','cuda','ffmpeg','ffprobe','model'))
            data['status']='ready' if data['ready'] else 'missing'
            missing=[label for key,label in [('backend','分离组件'),('cuda','GPU 运算'),('ffmpeg','FFmpeg'),('ffprobe','ffprobe'),('model','分离模型')] if not data[key]]
            data['message']='运行环境已就绪，可以导入并分离。' if data['ready'] else '尚未就绪：'+'、'.join(missing)
        except Exception as error:
            data={'status':'missing','ready':False,'message':'环境检查未通过。','error':str(error)}
        with self.lock:self.environment=data

    def prepare(self):
        with self.lock:
            if self.environment['status'] in ('checking','installing') or any(t['status'] in ('queued','running') for t in self.tasks):
                raise ValueError('正在处理任务，请等待完成后再准备环境。')
            script=self.app_root/'prepare_and_preview.py'
            if not script.exists():script=self.app_root/'scripts/windows_backend/prepare_and_preview.py'
            if not script.is_file():raise ValueError('缺少安装工具，请使用完整程序包。')
            self.setup_log=self.root/'reports'/f'setup-{uuid.uuid4().hex}.log'
            self.environment={'status':'installing','ready':False,'message':'正在准备分离组件，请保留程序窗口…'}
            self.executor.submit(self._prepare,script,self.setup_log)
            return dict(self.environment)

    def _prepare(self, script, logfile):
        try:
            with logfile.open('w',encoding='utf-8') as stream:
                result=subprocess.run([self.python,'-u',str(script),'--install-only'],stdout=stream,stderr=subprocess.STDOUT,timeout=3600)
            if result.returncode:raise RuntimeError('安装未完成，请展开运行记录查看原因。')
            self._probe()
        except Exception as error:
            with self.lock:self.environment={'status':'failed','ready':False,'message':str(error)}

    def enqueue(self, asset_ids, force=False):
        if not isinstance(asset_ids,list) or not asset_ids or len(asset_ids)>500 or any(not isinstance(x,str) for x in asset_ids):
            raise ValueError('请选择至少一份有效素材。')
        if type(force) is not bool:raise ValueError('重做选项格式错误。')
        with self.lock:
            if not self.environment['ready']:raise ValueError('请先完成运行环境准备。')
            with Library(self.root) as library:
                assets=[library.asset(x) for x in dict.fromkeys(asset_ids)]
            active={t['asset_id'] for t in self.tasks if t['status'] in ('queued','running')}
            queued=[]
            for asset in assets:
                if asset['id'] in active:continue
                task={'id':uuid.uuid4().hex,'asset_id':asset['id'],'filename':asset['filename'],
                      'status':'queued','created_at':now(),'job_id':None,'error':None}
                self.tasks.append(task);queued.append(dict(task));active.add(asset['id'])
                self.executor.submit(self._separate,task,force)
            return {'queued':queued,'count':len(queued)}

    def _separate(self, task, force):
        with self.lock:task.update(status='running',started_at=now())
        try:
            if not self._model_files():raise ValueError('分离模型缺失，请准备运行组件。')
            for name,expected in ((MODEL,MODEL_SHA),(MODEL.replace('.ckpt','.yaml'),CONFIG_SHA)):
                if digest(self.root/'models'/name)!=expected:raise ValueError('模型校验失败，请恢复完整模型文件。')
            with Library(self.root) as library:
                result=library.separate(task['asset_id'],MODEL,self.python,timeout=14400,force=force,
                                        mdxc_params=PARAMS,require_cuda=True)
            with self.lock:task.update(status='completed',job_id=result['id'],cached=result['status']=='cached',finished_at=now())
        except Exception as error:
            with self.lock:task.update(status='failed',error=str(error),finished_at=now())

    def status(self):
        with self.lock:
            tasks=[dict(t) for t in self.tasks]
            environment=dict(self.environment)
            setup_log=self.setup_log
        with Library(self.root) as library:
            assets=library.assets()
            for asset in assets:
                jobs=list(library.db.execute('SELECT id,status,error FROM jobs WHERE asset_id=? ORDER BY started_at DESC',(asset['id'],)))
                asset['successful_jobs']=sum(j['status']=='succeeded' for j in jobs)
                asset['latest_status']=jobs[0]['status'] if jobs else 'unprocessed'
            for task in tasks:
                job_id=task.get('job_id')
                if not job_id and task.get('started_at'):
                    row=library.db.execute('SELECT id FROM jobs WHERE asset_id=? AND started_at>=? ORDER BY started_at DESC LIMIT 1',
                                            (task['asset_id'],task['started_at'])).fetchone()
                    job_id=row['id'] if row else None
                if job_id:
                    log=tail(self.root/'preprocessing'/job_id/'backend.log')
                    task['log']=log
                    percents=re.findall(r'(\d+)%\|',log)
                    task['progress']=int(percents[-1]) if percents else None
        return {'assets':assets,'tasks':tasks,'environment':environment,'setup_log':tail(setup_log) if setup_log else ''}

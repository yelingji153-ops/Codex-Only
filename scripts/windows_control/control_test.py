"""Local diagnostic only: no training, package installation, or audio upload."""
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback
from urllib.parse import urlsplit, unquote, quote
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT/'training-backend/Applio-c817f1f83f689ef72e0dfeb1c17ae990b9248506'
LIBRARY = ROOT/'workspace-data'
EXPERIMENT = LIBRARY/'training/acane_38f8801be33b8849'
MODEL = EXPERIMENT/'models/acane_38f8801be33b8849/acane_38f8801be33b8849_30e_6270s.pth'
CATALOG_REPO = 'wok000/vcclient_model'
CATALOG_FILE = 'samples_0004_t.json'
SAMPLE_ID = 'Tsukuyomi-chan_t'
SOURCE_REFERENCE = 'https://github.com/w-okada/voice-changer/blob/d8ef15799470193f7c8176ef471245753a656626/server/const.py'
MAX_MODEL_BYTES = 600*1024*1024


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.json.tmp')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    part.replace(path)


def read_json_url(url):
    with urlopen(url, timeout=60) as response:
        data = response.read(8*1024*1024+1)
    if len(data)>8*1024*1024:
        raise ValueError('远程清单过大，已停止。')
    return json.loads(data)


def revision(repo):
    info = read_json_url('https://huggingface.co/api/models/'+repo)
    commit = info['sha']
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('远程模型版本无效。')
    return commit


def hf_location(url):
    u = urlsplit(url)
    parts = u.path.strip('/').split('/')
    if u.scheme!='https' or u.hostname!='huggingface.co' or len(parts)<5 or parts[2] not in ('resolve','raw'):
        raise ValueError('示例模型地址不符合预期，未继续下载。')
    repo='/'.join(parts[:2]); rev=parts[3]; file=unquote('/'.join(parts[4:]))
    if any(p in ('..','') for p in file.split('/')):
        raise ValueError('远程文件路径无效。')
    return repo,rev,file


def select_sample(catalog):
    entries = catalog.get('RVC',[]) if isinstance(catalog,dict) else []
    found = [e for e in entries if e.get('id')==SAMPLE_ID and e.get('voiceChangerType','RVC')=='RVC']
    if len(found)!=1:
        raise ValueError('项目示例清单已变化，未找到指定对照。请发送 control-test-log.txt，不要另装环境。')
    entry=found[0]
    _,_,name=hf_location(entry['modelUrl'])
    if not name.lower().endswith('.pth') or entry.get('f0') is False:
        raise ValueError('指定示例不是带音高的 PyTorch RVC 模型。')
    return entry


def fetch(url, target, expected=None, expected_size=None):
    if target.exists() and expected and sha(target)==expected:
        print('复用已校验文件：', target.name, flush=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part=target.with_suffix('.part')
    try:
        with urlopen(url,timeout=90) as response:
            total=int(response.headers.get('Content-Length') or expected_size or 0)
            if total>MAX_MODEL_BYTES:
                raise ValueError('模型超过 600 MiB 诊断下载上限，已停止。')
            print(f'下载候选声线模型：{total/1048576:.1f} MiB' if total else '下载候选声线模型：服务器未提供总大小',flush=True)
            done=0; last=time.monotonic(); start=last
            with part.open('wb') as stream:
                while block:=response.read(1024*1024):
                    done+=len(block)
                    if done>MAX_MODEL_BYTES:
                        raise ValueError('下载超过大小上限。')
                    stream.write(block)
                    now=time.monotonic()
                    if now-last>2 or (total and done==total):
                        percent=f'{100*done/total:.1f}%' if total else '总大小未知'
                        print(f'{done/1048576:.1f}/{total/1048576:.1f} MiB  {percent}  {done/1048576/max(now-start,.001):.2f} MiB/s',flush=True)
                        last=now
        if not done or (total and done!=total) or (expected_size and done!=expected_size):
            raise ValueError('模型下载不完整。')
        if expected and sha(part)!=expected:
            raise ValueError('模型 SHA-256 不符。')
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def acquire_candidate():
    cache=LIBRARY/'diagnostics/control-model'
    cache.mkdir(parents=True,exist_ok=True)
    lockpath=cache/'source.json'; target=cache/'candidate.pth'
    if lockpath.exists():
        record=json.loads(lockpath.read_text(encoding='utf-8'))
        hf_location(record['download_url'])
        fetch(record['download_url'],target,record.get('sha256'),record.get('size'))
        return target,record
    commit=revision(CATALOG_REPO)
    catalog=read_json_url(f'https://huggingface.co/{CATALOG_REPO}/raw/{commit}/{CATALOG_FILE}')
    entry=select_sample(catalog)
    repo,branch,file=hf_location(entry['modelUrl'])
    # Resolve this exact requested revision; never silently substitute another model.
    api='https://huggingface.co/api/models/'+repo+'/revision/'+quote(branch,safe='')+'?blobs=true'
    info=read_json_url(api); model_commit=info['sha']
    if len(model_commit)!=40 or any(c not in '0123456789abcdef' for c in model_commit):
        raise ValueError('模型版本号无效。')
    matches=[x for x in info.get('siblings',[]) if x.get('rfilename')==file]
    if len(matches)!=1:
        raise ValueError('模型源清单缺少指定文件。')
    meta=matches[0]; expected=meta.get('lfs',{}).get('sha256'); size=meta.get('size')
    url=f'https://huggingface.co/{repo}/resolve/{model_commit}/{quote(file,safe="/")}'
    record={'source_reference':SOURCE_REFERENCE,'catalog_revision':commit,'sample':entry,
            'model_revision':model_commit,'download_url':url,'size':size,'sha256':expected,
            'independently_listened_and_validated':False}
    print('候选模型：',entry.get('name',SAMPLE_ID), '\n署名：',entry.get('credit','见来源清单'),flush=True)
    print('它是项目提供的对照候选，歌唱自然度待试听。',flush=True)
    print('使用说明：',entry.get('termsOfUseUrl','https://github.com/w-okada/voice-changer#terms-of-use'),flush=True)
    fetch(url,target,expected,size)
    record['sha256']=sha(target);record['size']=target.stat().st_size
    save(lockpath,record)
    return target,record


def check_model(path):
    import torch
    model=torch.load(path,map_location='cpu',weights_only=True)
    if not isinstance(model,dict) or not isinstance(model.get('weight'),dict) or not isinstance(model.get('config'),(list,tuple)):
        raise ValueError('不是可用于推理的声线模型。')
    version=model.get('version','v1');voc=model.get('vocoder','HiFi-GAN')
    if version not in ('v1','v2') or voc!='HiFi-GAN' or not model.get('f0',1) or model['config'][-1] not in (32000,40000,48000):
        raise ValueError('候选模型结构不兼容，未执行转换。')
    embed=model.get('embedder_model')
    if embed not in (None,'','contentvec','hubert','hubert_base'):
        raise ValueError('模型需要另一种嵌入器，未自动下载。')
    w=model['weight'];dim=768 if version=='v2' else 256
    if 'enc_p.emb_phone.weight' not in w or w['enc_p.emb_phone.weight'].shape[1]!=dim or 'emb_g.weight' not in w:
        raise ValueError('模型特征维度与标准 RVC 不符。')
    if any(not torch.is_tensor(v) or not torch.isfinite(v).all() for v in w.values()):
        raise ValueError('模型权重无效。')
    return {'version':version,'vocoder':voc,'sample_rate':model['config'][-1],'feature_dim':dim,'sha256':sha(path)}


def audio_info(path, expected_duration=None):
    import numpy as np
    import soundfile as sf
    y,sr=sf.read(path,always_2d=True)
    if not y.size or not np.isfinite(y).all() or np.max(np.abs(y))==0:
        raise ValueError('输出为空、全静音或包含非有限值。')
    duration=len(y)/sr
    if expected_duration is not None and abs(duration-expected_duration)>.15:
        raise ValueError('转换输出时长不符，不能显示测试完成。')
    return {'duration':duration,'sample_rate':sr,'channels':y.shape[1],'sha256':sha(path)}


def worker(model, source, output):
    import numpy as np
    import torch
    if not torch.cuda.is_available():
        raise ValueError('CUDA 不可用，已停止。')
    metadata=check_model(model)
    random.seed(1234);np.random.seed(1234);torch.manual_seed(1234);torch.cuda.manual_seed_all(1234)
    sys.path.insert(0,str(BACKEND))
    from rvc.infer.infer import VoiceConverter
    converter=VoiceConverter()
    converter.convert_audio(audio_input_path=str(source),audio_output_path=str(output),model_path=str(model),
                            index_path='',inference_engine='torch',pitch=0,f0_method='rmvpe',
                            index_rate=0,protect=.33,volume_envelope=1,embedder_model='contentvec',export_format='WAV')
    info=audio_info(output,audio_info(source)['duration'])
    save(output.with_suffix('.json'),{'model':metadata,'audio':info,'seed':1234,
         'pitch':0,'f0_method':'rmvpe','index_rate':0,'protect':.33,'volume_envelope':1})


def command(args, cwd=ROOT, env=None):
    subprocess.run(list(map(str,args)),cwd=cwd,env=env,check=True)


def match_listening(files, folder, ffmpeg):
    # Same-channel, same-duration static RMS matching; no compression, EQ, or de-noising.
    import numpy as np
    import soundfile as sf
    prepared=[]
    for label,path in files:
        converted=folder/(label+'_mono48.wav')
        command([ffmpeg,'-nostdin','-v','error','-n','-i',path,'-ar','48000','-ac','1','-c:a','pcm_f32le',converted])
        y,sr=sf.read(converted,dtype='float64')
        prepared.append((label,y))
    count=min(len(y) for _,y in prepared)
    prepared=[(label,y[:count]) for label,y in prepared]
    source=prepared[0][1]
    frames=np.sqrt(np.mean(source[:len(source)//960*960].reshape(-1,960)**2,axis=1))
    mask=np.repeat(frames>max(frames.max()*.03,1e-6),960)
    mask=np.pad(mask,(0,count-len(mask)))
    if not mask.any():raise ValueError('选定片段没有足够有效信号，请换测试起点。')
    scales=[]
    for label,y in prepared:
        rms=float(np.sqrt(np.mean(y[mask]**2)))
        if rms<1e-8:raise ValueError('试听片段过于安静。')
        scales.append(.1/rms)
    peak=max(float(np.max(np.abs(y)))*g for (_,y),g in zip(prepared,scales))
    common=min(1,.89/max(peak,1e-8));result=[]
    for (label,y),gain in zip(prepared,scales):
        gain*=common;out=folder/(label+'_listen.wav')
        sf.write(out,y*gain,48000,subtype='PCM_16')
        result.append({'label':label,'path':out.name,'gain_db':float(20*np.log10(gain)),'duration':count/48000,'sha256':sha(out)})
    return result


def main():
    if os.name!='nt':raise ValueError('请在本机 Windows 运行。')
    import torch
    if not torch.cuda.is_available():raise ValueError('现有训练环境未检测到 CUDA。')
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    source=ROOT/'test.wav'
    for path in (ffmpeg,source,MODEL,BACKEND/'rvc/infer/infer.py'):
        if not path.exists():raise FileNotFoundError(f'找不到：{path}。请解压到原工作台文件夹。')
    settings={'start_s':10,'duration_s':20}
    settings_path=ROOT/'control-addon/settings.json'
    if settings_path.exists():settings.update(json.loads(settings_path.read_text(encoding='utf-8')))
    start=float(settings['start_s']);duration=float(settings['duration_s'])
    import math
    if not math.isfinite(start) or not math.isfinite(duration) or start<0 or not 5<=duration<=30:
        raise ValueError('测试起点必须非负，长度在 5～30 秒之间。')
    original_info=audio_info(source)
    if start+duration>original_info['duration']:
        raise ValueError('test.wav 太短；请修改 control-addon/settings.json 的起点和时长。')
    check_model(MODEL)
    candidate,provenance=acquire_candidate();candidate_meta=check_model(candidate)
    folder=LIBRARY/'diagnostics'/('control_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    report={'status':'running','source':original_info,'start_s':start,'duration_s':duration,
            'candidate_source':provenance,'candidate_model':candidate_meta,
            'purpose':'diagnostic candidate, not independently validated singing reference'}
    save(folder/'report.json',report)
    try:
        clip=folder/'01_original.wav'
        command([ffmpeg,'-nostdin','-v','error','-n','-ss',start,'-i',source,'-t',duration,'-ac','1','-ar','48000','-c:a','pcm_f32le',clip])
        env=dict(os.environ,PYTHONUTF8='1',PYTHONUNBUFFERED='1',APPLIO_ROOT=str(BACKEND),APPLIO_CODE_ROOT=str(BACKEND),
                 APPLIO_CONFIG_FILE=str(EXPERIMENT/'config.json'),APPLIO_LOGS_DIR=str(EXPERIMENT/'models'))
        files=[('01_original',clip)]
        for label,model in [('02_acane30',MODEL),('03_candidate',candidate)]:
            print('\n开始转换：'+label+'，两者均关闭索引、保持原音高。',flush=True)
            output=folder/(label+'.wav')
            command([sys.executable,Path(__file__).resolve(),'--worker',model,clip,output],BACKEND,env)
            audio_info(output,duration);files.append((label,output))
        report['listening']=match_listening(files,folder,ffmpeg)
        report['status']='completed';save(folder/'report.json',report)
        print('\n对照文件已生成。请比较 02_acane30_listen.wav 与 03_candidate_listen.wav。',flush=True)
        print('候选模型的音色不同，只比较自然度/清晰度；它的歌唱表现尚未证明合格。',flush=True)
        print('目录：'+str(folder),flush=True)
        os.startfile(folder)
    except BaseException as exc:
        report['status']='failed';report['error']=str(exc);save(folder/'report.json',report);raise


if __name__=='__main__':
    try:
        if len(sys.argv)>1 and sys.argv[1]=='--worker':
            worker(*map(Path,sys.argv[2:5]))
        else:main()
    except BaseException:
        message=traceback.format_exc();print(message,flush=True)
        with (ROOT/'control-test-log.txt').open('a',encoding='utf-8') as log:log.write(message+'\n')
        print('对照未完成。请发送 control-test-log.txt；不用重新安装训练环境。',flush=True)
        sys.exit(1)

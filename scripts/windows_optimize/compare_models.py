"""Local checkpoint listening comparison; never downloads candidate models."""
from pathlib import Path
import os
import sys
import time
import uuid
import traceback
import control_helpers as helper
from optimize_training import BASE, ROOT


def select_models(exp):
    found=[]
    for epoch in (30, 50, 70, 100):
        candidates=list(exp.glob(f'{exp.name}_{epoch}e_*s.pth'))
        if len(candidates)>1:
            raise ValueError('同一轮存在多个模型，请保留明确的一份后比较。')
        if candidates:
            found.append((f'new_{epoch:03d}e',candidates[0]))
    if not found:
        raise ValueError('尚未找到新实验 30/50/70/100 轮模型。')
    return found


def main():
    if os.name!='nt':raise RuntimeError('请在 Windows 本机运行。')
    source=ROOT/'test.wav'
    info=helper.audio_info(source)
    start=10 if info['duration']>=30 else 0
    duration=min(20,info['duration']-start)
    if duration<5:raise ValueError('test.wav 至少需要 5 秒干净人声。')
    name=BASE+'_opt100';run=ROOT/'workspace-data/training'/name
    exp=run/'models'/name
    backup=helper.MODEL.parent/'backup-before-opt100'/helper.MODEL.name
    baseline=backup if backup.exists() else helper.MODEL
    models=[('old_030e',baseline),*select_models(exp)]
    for _,model in models:helper.check_model(model)
    folder=run/'comparisons'/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);folder.mkdir(parents=True)
    ffmpeg=ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    clip=folder/'original.wav'
    helper.command([ffmpeg,'-nostdin','-v','error','-n','-ss',start,'-i',source,'-t',duration,'-ac','1','-ar',48000,'-c:a','pcm_f32le',clip])
    env=dict(os.environ,PYTHONUTF8='1',PYTHONUNBUFFERED='1',APPLIO_ROOT=str(helper.BACKEND),APPLIO_CODE_ROOT=str(helper.BACKEND),APPLIO_CONFIG_FILE=str(run/'config.json'),APPLIO_LOGS_DIR=str(run/'models'))
    files=[('original',clip)]
    for label,model in models:
        print('转换试听：'+label,flush=True)
        out=folder/(label+'.wav')
        helper.command([sys.executable,Path(__file__).with_name('control_helpers.py'),'--worker',model,clip,out],helper.BACKEND,env)
        helper.audio_info(out,duration);files.append((label,out))
    results=helper.match_listening(files,folder,ffmpeg)
    helper.save(folder/'comparison.json',{'source':info,'start_s':start,'duration_s':duration,'outputs':results,'note':'Same seed, RMVPE, pitch 0, index 0, matched static RMS; no automatic quality ranking.'})
    print('请比较 *_listen.wav；按自然度、清晰度和相似度选模型。',flush=True)
    os.startfile(str(folder))


if __name__=='__main__':
    try:main()
    except BaseException:
        msg=traceback.format_exc();print(msg,flush=True)
        (ROOT/'compare-100-error.txt').write_text(msg,encoding='utf-8');sys.exit(1)

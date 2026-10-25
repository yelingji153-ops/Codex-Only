"""Back up legacy conversion slots and install a verified model/index pair."""
import json
from pathlib import Path
import shutil
from optimize_training import digest, save


def activate(exp, original, base):
    models=list(exp.glob(f'{exp.name}_100e_*s.pth'))
    if len(models)!=1:raise ValueError('必须有且只有一份完成 100 轮的模型。')
    pairs=[(models[0], original/(base+'_30e_6270s.pth')),
           (exp/(exp.name+'.index'),original/(base+'.index'))]
    backup=original/'backup-before-opt100'
    manifest=backup/'manifest.json'
    active=original/'active-model.json'
    wanted={dst.name:digest(src) for src,dst in pairs}
    if active.exists():
        last=json.loads(active.read_text(encoding='utf-8'))
        if last.get('installed_hashes')==wanted and all(digest(dst)==wanted[dst.name] for _,dst in pairs):
            return
    if not manifest.exists():
        if backup.exists():raise ValueError('备份未完成，请保留备份目录并联系排查。')
        backup.mkdir()
        hashes={}
        for _,dst in pairs:
            shutil.copyfile(dst,backup/dst.name)
            hashes[dst.name]=digest(dst)
            if digest(backup/dst.name)!=hashes[dst.name]:raise ValueError('旧模型备份校验失败。')
        save(manifest,{'original_hashes':hashes})
    old=json.loads(manifest.read_text(encoding='utf-8'))['original_hashes']
    for _,dst in pairs:
        if digest(backup/dst.name)!=old[dst.name]:raise ValueError('旧模型备份已改变，停止替换。')
    # Stage both files before replacing either. On normal failure restore both.
    for src,dst in pairs:
        temp=dst.with_suffix(dst.suffix+'.installing')
        shutil.copyfile(src,temp)
        if digest(temp)!=wanted[dst.name]:raise ValueError('新模型复制校验失败。')
    try:
        for _,dst in pairs:dst.with_suffix(dst.suffix+'.installing').replace(dst)
        save(active,{'epoch':100,'experiment':exp.name,'installed_hashes':wanted,
                     'backup':str(backup),'note':'Legacy 30e filename retained only for existing commands; contents are the new 100e model.'})
    except BaseException:
        for _,dst in pairs:
            temp=dst.with_suffix(dst.suffix+'.restoring')
            shutil.copyfile(backup/dst.name,temp);temp.replace(dst)
        raise
    print('新 100 轮模型与索引已接替原转换路径。旧版备份：'+str(backup),flush=True)

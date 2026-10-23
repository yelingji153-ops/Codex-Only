"""Build the local app around an already validated Windows CUDA environment.

Dependencies, model files and generated archives stay outside Git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'model_bs_roformer_ep_317_sdr_12.9755.ckpt'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(args):
    payload, models = Path(args.payload), Path(args.models)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT/'scripts/windows_backend/download-manifest.json').read_text())
    if digest(args.ffmpeg) != manifest['ffmpeg_sha256']:
        raise ValueError('FFmpeg archive checksum mismatch')
    for name, expected in [(MODEL, manifest['model_sha256']),
                           (MODEL.replace('.ckpt','.yaml'), manifest['config_sha256'])]:
        if digest(models/name) != expected:
            raise ValueError('Model checksum mismatch: '+name)
    lock = json.loads((payload/'offline-wheels.json').read_text())
    for item in lock['wheels']:
        if Path(item['filename']).name != item['filename']:
            raise ValueError('Unsafe wheel path')
        if digest(payload/'wheelhouse'/item['filename']) != item['sha256']:
            raise ValueError('Wheel checksum mismatch: '+item['filename'])
    with tempfile.TemporaryDirectory(prefix='acane-app-') as directory:
        stage = Path(directory)/'ACAne-GPU-Setup-v2'
        stage.mkdir()
        shutil.copytree(ROOT/'acane', stage/'acane', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy2(ROOT/'Start_ACAne.cmd', stage/'Start_ACAne.cmd')
        for name in ('prepare_and_preview.py','constraints.txt'):
            shutil.copy2(ROOT/'scripts/windows_backend'/name, stage/name)
        for name in ('offline-wheels.json','offline-requirements.txt'):
            shutil.copy2(payload/name, stage/name)
        shutil.copytree(payload/'wheelhouse', stage/'wheelhouse')
        (stage/'models').mkdir()
        for name in (MODEL, MODEL.replace('.ckpt','.yaml'), 'download_checks.json','mdx_model_data.json','vr_model_data.json'):
            shutil.copy2(models/name, stage/'models'/name)
        bindir = stage/'tools/ffmpeg/bin'
        bindir.mkdir(parents=True)
        hashes = {}
        with zipfile.ZipFile(args.ffmpeg) as archive:
            if archive.testzip():
                raise ValueError('FFmpeg ZIP integrity failure')
            for name in ('ffmpeg.exe','ffprobe.exe'):
                members = [x for x in archive.namelist() if x.endswith('/bin/'+name)]
                if len(members) != 1:
                    raise ValueError('Missing FFmpeg executable')
                with archive.open(members[0]) as source, (bindir/name).open('wb') as dest:
                    shutil.copyfileobj(source, dest)
                hashes[name] = digest(bindir/name)
            for member in archive.namelist():
                if Path(member).name.lower() in ('license','license.txt','readme.txt'):
                    (stage/'tools/ffmpeg'/Path(member).name).write_bytes(archive.read(member))
        manifest.update(offline_mode=True,ffmpeg_binaries_sha256=hashes)
        (stage/'download-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        shutil.copy2(ROOT/'docs/local-app.md',stage/'使用说明.md')
        file_hashes = {p.relative_to(stage).as_posix():digest(p) for p in stage.rglob('*') if p.is_file()}
        (stage/'bundle-sha256.json').write_text(json.dumps(file_hashes,indent=2),encoding='utf-8')
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    archive.write(path,path.relative_to(stage.parent))
        with zipfile.ZipFile(output) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError('Bundle ZIP integrity failure: '+bad)
    result={'archive':str(output),'bytes':output.stat().st_size,'sha256':digest(output),
            'wheel_count':len(lock['wheels']),'zip_crc_verified':True,'windows_inference_tested':False}
    output.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    for name in ('payload','models','ffmpeg','output'):
        parser.add_argument('--'+name,required=True)
    build(parser.parse_args())

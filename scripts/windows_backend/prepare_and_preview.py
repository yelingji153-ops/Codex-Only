"""Prepare the existing Windows CUDA environment and verify one real preview."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
import zipfile

BASE = Path(__file__).resolve().parent
MODEL = 'model_bs_roformer_ep_317_sdr_12.9755.ckpt'
PARAMS = dict(segment_size=256, override_model_segment_size=True, overlap=2, batch_size=1)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, target, expected):
    """Keep complete verified files; never accept a partial download as a model."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(target) != expected:
            raise ValueError(f'Existing file hash mismatch; file preserved: {target}')
        print('Using verified cache:', target.name, flush=True)
        return
    partial = target.with_suffix(target.suffix + '.partial')
    print('Downloading:', target.name, flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as stream:
        total = int(response.headers.get('Content-Length') or 0)
        received = 0
        previous = 0.0
        while block := response.read(1024 * 1024):
            stream.write(block)
            received += len(block)
            if time.monotonic() - previous >= 2:
                print(f'  {received / 1048576:.1f} / {total / 1048576:.1f} MiB', flush=True)
                previous = time.monotonic()
    if digest(partial) != expected:
        raise ValueError(f'Download hash mismatch: {partial}')
    partial.replace(target)


def install_ffmpeg(manifest):
    archive = BASE / 'downloads/ffmpeg-7.1.1.zip'
    download(manifest['ffmpeg_url'], archive, manifest['ffmpeg_sha256'])
    bindir = BASE / 'tools/ffmpeg/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    # Extract only the two executables by basename; archive paths are never used.
    with zipfile.ZipFile(archive) as z:
        for name in ('ffmpeg.exe', 'ffprobe.exe'):
            matches = [p for p in z.namelist() if p.endswith('/bin/' + name)]
            if len(matches) != 1:
                raise ValueError(f'Unexpected FFmpeg archive: {name}')
            target = bindir / name
            temp = target.with_suffix('.partial')
            with z.open(matches[0]) as source, temp.open('wb') as dest:
                shutil.copyfileobj(source, dest)
            temp.replace(target)
    os.environ['PATH'] = str(bindir) + os.pathsep + os.environ.get('PATH', '')
    for name in ('ffmpeg', 'ffprobe'):
        subprocess.run([name, '-version'], check=True, stdout=subprocess.DEVNULL)


def preview(manifest):
    import numpy as np
    import soundfile as sf
    import torch
    from audio_separator.separator import Separator

    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; refusing to silently run this preview on CPU.')
    source = BASE / 'sample/TAIDADA_10s.wav'
    if digest(source) != manifest['sample_sha256']:
        raise ValueError('Sample integrity check failed.')
    models = BASE / 'models'
    download(manifest['model_url'], models / MODEL, manifest['model_sha256'])
    if digest(models / MODEL.replace('.ckpt', '.yaml')) != manifest['config_sha256']:
        raise ValueError('Model configuration hash mismatch.')
    output = BASE / 'preview-results' / time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    separator = Separator(output_dir=str(output), model_file_dir=str(models), output_format='WAV', mdxc_params=PARAMS)
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    separator.load_model(model_filename=MODEL)
    instance = separator.model_instance
    if instance.torch_device.type != 'cuda' or next(instance.model_run.parameters()).device.type != 'cuda':
        raise RuntimeError('Model weights are not on CUDA.')
    files = separator.separate(str(source))
    torch.cuda.synchronize()
    seconds = time.perf_counter() - start
    records = []
    stems = set()
    for filename in files:
        path = Path(filename)
        if not path.is_absolute():
            path = output / path
        path = path.resolve()
        if not path.is_relative_to(output.resolve()):
            raise ValueError('Unexpected model output path.')
        data, rate = sf.read(path, always_2d=True)
        if not data.size or not np.isfinite(data).all() or abs(len(data) / rate - 10) > 0.1:
            raise ValueError('Invalid preview audio output.')
        stem = 'Vocals' if '(Vocals)' in path.name else 'Instrumental' if '(Instrumental)' in path.name else None
        if stem is None or stem in stems:
            raise ValueError('Unexpected or duplicate audio stem.')
        stems.add(stem)
        mp3 = output / (stem + '.mp3')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(path), '-c:a', 'libmp3lame', '-b:a', '192k', str(mp3)], check=True)
        records.append({'stem': stem, 'wav': str(path), 'mp3': str(mp3), 'sha256': digest(path), 'seconds': len(data) / rate})
    if stems != {'Vocals', 'Instrumental'}:
        raise ValueError('Two output stems are required.')
    return {'model_inference_tested': True, 'model_inference_passed': True,
            'device': torch.cuda.get_device_name(0), 'model_device': str(instance.torch_device),
            'model': MODEL, 'parameters': PARAMS, 'model_sha256': manifest['model_sha256'],
            'config_sha256': manifest['config_sha256'], 'sample_sha256': manifest['sample_sha256'],
            'elapsed_seconds_including_model_load': seconds,
            'peak_cuda_allocated_mib': torch.cuda.max_memory_allocated() / 1048576,
            'torch': torch.__version__, 'audio_separator': importlib.metadata.version('audio-separator'),
            'outputs': records, 'review': 'Local output awaits listening; no batch or training started.'}


def main():
    os.chdir(BASE)
    report = {'status': 'running', 'stage': 'environment', 'model_inference_tested': False,
              'model_inference_passed': False}
    report_path = BASE / 'backend-check-report.json'
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        if sys.platform != 'win32' or sys.version_info[:2] != (3, 12):
            raise RuntimeError('Use the existing Windows Python 3.12 environment.')
        for name, expected in [('torch', '2.8.0+cu128'), ('torchvision', '0.23.0+cu128')]:
            if importlib.metadata.version(name) != expected:
                raise RuntimeError(f'Expected the previously validated {name} {expected}.')
        manifest = json.loads((BASE / 'download-manifest.json').read_text(encoding='utf-8'))
        report['stage'] = 'install_dependencies'
        print('[1/3] Installing separation dependencies. Download progress is visible below.', flush=True)
        subprocess.run([sys.executable, '-m', 'pip', '--log', str(BASE / 'backend-pip-log.txt'),
                        'install', '--disable-pip-version-check', '--only-binary=:all:',
                        '--progress-bar', 'on', '--timeout', '60', '--retries', '3',
                        '--index-url', 'https://pypi.org/simple',
                        '-c', str(BASE / 'constraints.txt'),
                        'audio-separator[gpu]==0.47.1', 'audioread==3.1.0', 'onnxruntime-gpu==1.23.2'], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
        report['stage'] = 'ffmpeg'
        print('[2/3] Preparing FFmpeg locally; system PATH is not modified.', flush=True)
        install_ffmpeg(manifest)
        report['stage'] = 'model_preview'
        print('[3/3] Downloading model if needed, then running the 10-second CUDA preview.', flush=True)
        report.update(preview(manifest))
        report['status'] = 'passed'
        print('Preview passed. Send backend-check-report.json and listen to Vocals.mp3.', flush=True)
    except Exception as exc:
        report.update(status='failed', error=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        print('Send backend-check-report.json; for install errors also send backend-pip-log.txt.', flush=True)
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())

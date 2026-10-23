"""Windows training add-on. The distributed directory is training-addon/."""
import contextlib
import hashlib
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

from acane.library import Library
from acane.media import digest
from acane.training_data import scan, snapshot

COMMIT = 'c817f1f83f689ef72e0dfeb1c17ae990b9248506'
ARCHIVE_SHA = '8b148c4d1a28bf5aed358e473b7e9d9c04208b1736ac06b52728d0c6c8eff3d5'
ROOT = Path(__file__).resolve().parent.parent


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def download(url, target, expected=None):
    if target.exists() and expected and digest(target) == expected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + '.part')
    for attempt in range(3):
        try:
            print('下载：', target.name, flush=True)
            with urllib.request.urlopen(url, timeout=90) as response, partial.open('wb') as out:
                size = int(response.headers.get('Content-Length', 0))
                done, last = 0, 0
                while block := response.read(1024*1024):
                    out.write(block)
                    done += len(block)
                    if time.monotonic()-last > 3:
                        print(f'  {done/1048576:.1f} / {size/1048576:.1f} MB', flush=True)
                        last = time.monotonic()
            if not done or (size and done != size) or (expected and digest(partial) != expected):
                raise ValueError('下载文件不完整或 SHA-256 不符。')
            partial.replace(target)
            return
        except Exception:
            partial.unlink(missing_ok=True)
            if attempt == 2:
                raise
            print('连接中断，正在重试。', flush=True)


def run(command, log, cwd=ROOT, env=None, interactive=False):
    print('执行：', ' '.join(map(str, command)), flush=True)
    with log.open('a', encoding='utf-8') as stream:
        stream.write('\nCOMMAND: '+repr(list(map(str, command)))+'\n')
        with subprocess.Popen(list(map(str, command)), cwd=cwd, env=env, stdout=None if interactive else subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace') as proc:
            try:
                if not interactive:
                    for line in proc.stdout:
                        print(line, end='', flush=True)
                        stream.write(line)
                        stream.flush()
                if proc.wait():
                    raise RuntimeError(f'步骤失败，详见 {log}')
            except BaseException:
                if proc.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
                raise


@contextlib.contextmanager
def exclusive(path):
    import msvcrt
    with path.open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('已有训练窗口正在运行，请勿重复启动。') from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def setup(log):
    backend = ROOT/'training-backend'/('Applio-'+COMMIT)
    if not (backend/'.acane-source-ready').exists():
        archive = ROOT/'training-addon'/'applio.zip'
        download(f'https://codeload.github.com/IAHispano/Applio/zip/{COMMIT}', archive, ARCHIVE_SHA)
        destination = backend.parent.resolve()
        destination.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not (destination/name).resolve().is_relative_to(destination):
                    raise ValueError('上游归档包含越界路径。')
            bundle.extractall(destination)
        (backend/'.acane-source-ready').write_text(ARCHIVE_SHA, encoding='ascii')
    python = ROOT/'.venv-training'/'Scripts'/'python.exe'
    if not python.exists():
        run([sys.executable, '-m', 'venv', ROOT/'.venv-training'], log)
    marker = ROOT/'.venv-training'/'acane-ready.json'
    if not marker.exists():
        print('首次安装独立训练组件，需要下载数 GB。分离环境保持原样。', flush=True)
        pip = [python, '-m', 'pip', '--log', ROOT/'training-pip-log.txt',
               'install', '--progress-bar', 'on', '--timeout', '90', '--retries', '5']
        run(pip+['torch==2.11.0+cu128', 'torchaudio==2.11.0+cu128', '--index-url', 'https://download.pytorch.org/whl/cu128'], log, interactive=True)
        constraints = ROOT/'training-addon'/'constraints.txt'
        constraints.write_text('torch==2.11.0+cu128\ntorchaudio==2.11.0+cu128\n', encoding='utf-8')
        run(pip+['-r', backend/'requirements-engine.txt', '-c', constraints], log, interactive=True)
        run([python, '-m', 'pip', 'check'], log)
        save(marker, {'backend_commit': COMMIT})
    return python, backend


def models(backend):
    # Resolve the upstream repository once, then retain immutable revision and hashes.
    lockfile = ROOT/'training-addon'/'models-lock.json'
    if lockfile.exists():
        lock = json.loads(lockfile.read_text(encoding='utf-8'))
    else:
        with urllib.request.urlopen('https://huggingface.co/api/models/IAHispano/Applio', timeout=60) as response:
            revision = json.load(response)['sha']
        if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision):
            raise ValueError('预训练资源版本号无效。')
        lock = {'revision': revision, 'files': {}}
        save(lockfile, lock)
    mapping = {
        'pretrained_v2/f0G40k.pth': 'pretraineds/hifi-gan/f0G40k.pth',
        'pretrained_v2/f0D40k.pth': 'pretraineds/hifi-gan/f0D40k.pth',
        'predictors/rmvpe.pt': 'predictors/rmvpe.pt',
        'embedders/contentvec/config.json': 'embedders/contentvec/config.json',
        'embedders/contentvec/pytorch_model.bin': 'embedders/contentvec/pytorch_model.bin',
    }
    for remote, local in mapping.items():
        url = f'https://huggingface.co/IAHispano/Applio/resolve/{lock["revision"]}/Resources/{remote}'
        target = backend/'rvc'/'models'/local
        download(url, target, lock['files'].get(remote, {}).get('sha256'))
        lock['files'][remote] = {'url': url, 'sha256': digest(target)}
        save(lockfile, lock)
    return lock


def main():
    if os.name != 'nt' or sys.version_info[:2] != (3, 12):
        raise RuntimeError('请使用 Windows Python 3.12 启动。')
    library_root = ROOT/'workspace-data'
    if not (library_root/'segments').is_dir():
        raise RuntimeError('请将补充包解压到 Start_ACAne.cmd 所在目录；没有找到 workspace-data/segments。')
    log = ROOT/'training-log.txt'
    with exclusive(ROOT/'training-addon'/'training.lock'):
        library = Library(library_root)
        try:
            selection = scan(library)
            folder = snapshot(library, selection)
        finally:
            library.db.close()
        print(f'已选 {len(selection["files"])} 段，{selection["duration"]/60:.1f} 分钟；跳过完全相同的片段 {len(selection["duplicates"])} 段。', flush=True)
        print('素材快照和模型保存位置：', folder, flush=True)
        state_path = folder/'state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'completed': []}
        try:
            state['status'] = 'preparing'
            save(state_path, state)
            python, backend = setup(log)
            env = dict(os.environ, APPLIO_ROOT=str(backend), APPLIO_CODE_ROOT=str(backend),
                       APPLIO_LOGS_DIR=str(folder/'models'), APPLIO_CONFIG_FILE=str(folder/'config.json'),
                       PYTHONUTF8='1', PYTHONUNBUFFERED='1', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
            save(folder/'config.json', {'precision': 'fp32'})
            verifier = ROOT/'training-addon'/'verify_training.py'
            run([python, verifier, 'gpu', folder], log, backend, env)
            save(folder/'pretrained-resources.json', models(backend))
            name = selection['id']
            exp = folder/'models'/name
            pre = backend/'rvc/models/pretraineds/hifi-gan'
            def stage(label, script, args, validation=None):
                state['status'] = label
                save(state_path, state)
                print('\n训练阶段：'+label, flush=True)
                if label not in state['completed']:
                    run([python, backend/script, *args], log, backend, env)
                if validation:
                    run([python, verifier, validation, exp], log, backend, env)
                if label not in state['completed']:
                    state['completed'].append(label)
                save(state_path, state)
            stage('preprocess', ROOT/'training-addon'/'prepare_audio.py',
                  [folder/'dataset', exp], 'audio')
            stage('extract', 'rvc/train/extract/extract.py', [exp, 'rmvpe', 2, '0', 40000, 'contentvec', 'None', 0], 'features')
            def train_args(epochs, interval):
                return [name, interval, epochs, pre/'f0G40k.pth', pre/'f0D40k.pth', '0', 2, 40000,
                        'True', 'True', 'False', 'False', 'HiFi-GAN', 'True']
            stage('train_one_epoch', 'rvc/train/train.py', train_args(1, 1), 'model1')
            stage('train_100_epochs', 'rvc/train/train.py', train_args(100, 10), 'model100')
            stage('index', 'rvc/train/process/extract_index.py', [exp, 'Auto'], 'index')
            state['status'] = 'completed'
            state['model_directory'] = str(exp)
            save(state_path, state)
            print('\n训练及索引生成完成，尚待歌声转换试听。模型目录：'+str(exp), flush=True)
        except BaseException as exc:
            state['status'] = 'failed'
            state['error'] = str(exc)
            save(state_path, state)
            raise


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        message = traceback.format_exc()
        print(message, flush=True)
        with (ROOT/'training-log.txt').open('a', encoding='utf-8') as stream:
            stream.write(message)
        print('训练未完成。请发送 training-log.txt 和 training-pip-log.txt；修复后重新双击可继续已有快照。', flush=True)
        sys.exit(1)

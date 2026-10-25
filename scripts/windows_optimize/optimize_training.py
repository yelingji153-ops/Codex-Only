"""Independent 100-epoch training experiment; no installation or downloads."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent.parent
BASE = 'acane_38f8801be33b8849'
COMMIT = 'c817f1f83f689ef72e0dfeb1c17ae990b9248506'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def prepare(source, target):
    import numpy as np
    import soundfile as sf
    records = json.loads((source/'prepared-audio.json').read_text(encoding='utf-8'))
    if not records or len({r['path'] for r in records}) != len(records):
        raise ValueError('切片清单为空或重复。')
    peaks, inputs = {}, {}
    for row in records:
        name = row['path']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('切片路径无效。')
        path = source/'sliced_audios'/name
        if not path.resolve().is_relative_to(source.resolve()):
            raise ValueError('切片路径越界。')
        y, sr = sf.read(path, dtype='float32')
        if sr != 40000 or y.ndim != 1 or len(y) < 16000 or not np.isfinite(y).all():
            raise ValueError('切片格式无效：'+name)
        peaks[row['source']] = max(peaks.get(row['source'], 0), float(np.max(np.abs(y))))
        inputs[name] = digest(path)
    gains = {key: 10**(-3/20)/peak if peak > 1 else 1.0 for key, peak in peaks.items()}
    expected = {'source_hashes': inputs, 'gains': gains, 'source_peaks': peaks,
                'policy': 'Only sources above 0 dBFS attenuated to -3 dBFS; shared gain across their slices.'}
    report_path = target/'level-report.json'
    if report_path.exists():
        old = json.loads(report_path.read_text(encoding='utf-8'))
        if any(old[k] != v for k, v in expected.items()):
            raise ValueError('原素材或电平策略发生变化，拒绝复用已有实验。')
        if {p.name for p in (target/'sliced_audios').glob('*.wav')} != set(inputs) or set(old['output_hashes']) != set(inputs):
            raise ValueError('实验切片集合已改变。')
        for name, sha in old['output_hashes'].items():
            if digest(target/'sliced_audios'/name) != sha:
                raise ValueError('实验副本已被修改。')
        return old
    if target.exists():
        raise ValueError('存在未完成的准备目录，请保留并重命名后重试：'+str(target))
    (target/'sliced_audios').mkdir(parents=True)
    outputs = {}
    import shutil
    for row in records:
        src = source/'sliced_audios'/row['path']
        dst = target/'sliced_audios'/row['path']
        gain = gains[row['source']]
        if digest(src) != inputs[row['path']]:
            raise ValueError('准备期间原文件发生变化。')
        if gain == 1:
            shutil.copyfile(src, dst)
        else:
            y, sr = sf.read(src, dtype='float32')
            sf.write(dst, y*gain, sr, subtype='FLOAT')
        outputs[row['path']] = digest(dst)
    for name in ('prepared-audio.json', 'model_info.json'):
        shutil.copyfile(source/name, target/name)
    expected['output_hashes'] = outputs
    expected['attenuated_sources'] = sum(g < 1 for g in gains.values())
    save(report_path, expected)
    return expected


def run(args, backend, env, log):
    with log.open('a', encoding='utf-8') as out:
        out.write('\n'+repr(list(map(str, args)))+'\n')
        with subprocess.Popen(list(map(str, args)), cwd=backend, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding='utf-8', errors='replace') as proc:
            try:
                for line in proc.stdout:
                    print(line, end='', flush=True)
                    out.write(line)
                    out.flush()
                if proc.wait():
                    raise RuntimeError('阶段失败，见 '+str(log))
            except BaseException:
                if proc.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
                    proc.wait()
                raise


def main():
    if os.name != 'nt':
        raise RuntimeError('请在原 Windows 训练目录运行。')
    import msvcrt
    # Same lock as the original launcher; don't launch manual training concurrently.
    with (ROOT/'training-addon'/'training.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        execute()


def configure(backend, exp, folder):
    config_path = exp/'config.json'
    recipe = {'epochs': 100, 'save_interval': 10, 'learning_rate': 0.0001,
              'lr_decay': 0.99, 'seed': 1234, 'batch_size': 2, 'precision': 'fp32',
              'backend_commit': COMMIT,
              'limitation': 'Experimental schedule, not established best quality; compare saved checkpoints.'}
    marker = folder/'recipe.json'
    if marker.exists():
        if json.loads(marker.read_text(encoding='utf-8')) != recipe:
            raise ValueError('训练配方已改变，不能混用续训。')
        config = json.loads(config_path.read_text(encoding='utf-8'))
        for key in ('learning_rate', 'lr_decay', 'seed'):
            if config['train'][key] != recipe[key]:
                raise ValueError('训练配置已修改，停止续训。')
        return
    if list(exp.glob('*.pth')):
        raise ValueError('新配方目录已有模型，拒绝继承未知检查点。')
    config = json.loads((backend/'rvc/configs/40000.json').read_text(encoding='utf-8'))
    for key in ('learning_rate', 'lr_decay', 'seed'):
        config['train'][key] = recipe[key]
    save(config_path, config)
    save(marker, recipe)


def execute():
    backend = ROOT/'training-backend'/('Applio-'+COMMIT)
    old_run = ROOT/'workspace-data'/'training'/BASE
    name = BASE+'_opt100'
    folder = old_run.parent/name
    exp = folder/'models'/name
    source = old_run/'models'/BASE
    verifier = ROOT/'optimize-addon'/'verify_training.py'
    python = ROOT/'.venv-training'/'Scripts'/'python.exe'
    pre = backend/'rvc/models/pretraineds/hifi-gan'
    # Verify recorded resources without calling the downloader or installer.
    resources = json.loads((old_run/'pretrained-resources.json').read_text(encoding='utf-8'))
    mapping = {'pretrained_v2/f0G40k.pth': pre/'f0G40k.pth',
               'pretrained_v2/f0D40k.pth': pre/'f0D40k.pth',
               'predictors/rmvpe.pt': backend/'rvc/models/predictors/rmvpe.pt',
               'embedders/contentvec/config.json': backend/'rvc/models/embedders/contentvec/config.json',
               'embedders/contentvec/pytorch_model.bin': backend/'rvc/models/embedders/contentvec/pytorch_model.bin'}
    for key, path in mapping.items():
        if digest(path) != resources['files'][key]['sha256']:
            raise ValueError('预训练资源校验失败：'+key)
    report = prepare(source, exp)
    print(f'共 {len(report["source_hashes"])} 切片；降低 {report["attenuated_sources"]} 个来源片段的电平。', flush=True)
    env = dict(os.environ, APPLIO_ROOT=str(backend), APPLIO_CODE_ROOT=str(backend),
               APPLIO_LOGS_DIR=str(folder/'models'), APPLIO_CONFIG_FILE=str(folder/'config.json'),
               PYTHONUTF8='1', PYTHONUNBUFFERED='1', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2')
    save(folder/'config.json', {'precision': 'fp32'})
    configure(backend, exp, folder)
    log = folder/'optimize-training-log.txt'
    state_path = folder/'optimize-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'completed': []}
    def call(args): run([python, *args], backend, env, log)
    call([verifier, 'gpu', folder])
    call([verifier, 'audio', exp])
    stages = [
        ('features', [backend/'rvc/train/extract/extract.py', exp, 'rmvpe', 2, '0', 40000, 'contentvec', 'None', 0], 'features'),
        ('train100', [backend/'rvc/train/train.py', name, 10, 100, pre/'f0G40k.pth', pre/'f0D40k.pth', '0', 2, 40000, 'True', 'True', 'False', 'False', 'HiFi-GAN', 'True'], 'model100'),
        ('index', [backend/'rvc/train/process/extract_index.py', exp, 'Auto'], 'index')]
    for label, args, check in stages:
        print('\n阶段：'+label, flush=True)
        if label not in state['completed']:
            call(args)
        call([verifier, check, exp])
        if label not in state['completed']:
            state['completed'].append(label)
        save(state_path, state)
    from activate_model import activate
    activate(exp, source, BASE)
    print('\n100 轮训练完成并已替换转换用模型。新模型归档：'+str(exp), flush=True)
    os.startfile(str(exp))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        message = traceback.format_exc()
        print(message, flush=True)
        (ROOT/'optimize-training-error.txt').write_text(message, encoding='utf-8')
        sys.exit(1)

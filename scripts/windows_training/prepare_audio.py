"""Resample disposable copies and preserve every tail, without normalization."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import soundfile as sf
import numpy as np
from acane.training_data import chunk_frames


def prepare(dataset, experiment):
    output = experiment/'sliced_audios'
    output.mkdir(parents=True, exist_ok=True)
    records = []
    skipped = []
    for index, source in enumerate(sorted(dataset.glob('*.wav'))):
        with tempfile.TemporaryDirectory(dir=experiment) as directory:
            converted = Path(directory)/'converted.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(source),
                            '-ar', '40000', '-ac', '1', '-c:a', 'pcm_f32le', str(converted)], check=True)
            values, rate = sf.read(converted, dtype='float32')
        if np.isfinite(values).all() and len(values) < int(.4*rate):
            item = {'source': source.name, 'duration_s': len(values)/rate,
                    'reason': 'shorter_than_0.4_seconds'}
            skipped.append(item)
            print(f'跳过过短片段：{source.name} ({item["duration_s"]:.3f} 秒)，原文件保留。', flush=True)
            continue
        if not np.isfinite(values).all() or not np.any(values):
            raise ValueError(f'片段含非有限数或完全静音：{source}')
        for chunk, (left, right) in enumerate(chunk_frames(len(values))):
            target = output/f'0_{index}_{chunk}.wav'
            sf.write(target, values[left:right], rate, subtype='FLOAT')
            records.append({'source': source.name, 'path': target.name, 'start_frame': left, 'end_frame': right})
    (experiment/'skipped-audio.json').write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding='utf-8')
    if len(records) < 6:
        raise ValueError('可用训练切片少于 6 段，当前 batch size 2 至少需要 3 个批次。')
    (experiment/'prepared-audio.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    info = {'total_dataset_duration': sum(r['end_frame']-r['start_frame'] for r in records)/40000}
    (experiment/'model_info.json').write_text(json.dumps(info), encoding='utf-8')
    print(f'Prepared {len(records)} segments; skipped {len(skipped)} short clips (see skipped-audio.json); tails retained, no gain normalization.')


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))

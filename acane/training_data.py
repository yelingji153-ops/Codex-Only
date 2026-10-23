"""Explicit all-saved selection, immutable training copies, no ML imports."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .media import digest, probe


def scan(library):
    root = library.root / 'segments'
    records, duplicates, seen = [], [], set()
    manifests = []
    for path in sorted(root.glob('*/manifest.json')):
        if path.parent.name.startswith('.'):
            continue
        if not path.resolve().is_relative_to(library.root):
            raise ValueError('片段清单位于资料库之外。')
        batch = json.loads(path.read_text(encoding='utf-8'))
        if batch['schema_version'] != 1 or batch['id'] != path.parent.name:
            raise ValueError(f'片段清单版本或编号不符：{path}')
        plan = batch['parent_plan']
        _, output, _, asset, _ = library._approved_segment_source(plan['job_id'], plan['output']['path'])
        if output['sha256'] != plan['output']['sha256'] or asset['id'] != plan['original']['id']:
            raise ValueError('片段来源与审核记录不符。')
        manifests.append({'path': str(path.relative_to(library.root)), 'sha256': digest(path), 'manifest': batch})
        for item in batch['files']:
            source = path.parent / item['path']
            if Path(item['path']).name != item['path'] or not source.resolve().is_relative_to(path.parent.resolve()):
                raise ValueError('片段路径越界。')
            if digest(source) != item['sha256']:
                raise ValueError(f'片段已被修改：{source}')
            info = probe(source)
            if abs(info['duration'] - item['metadata']['duration']) > .002:
                raise ValueError(f'片段时长不符：{source}')
            record = {'source': str(source.relative_to(library.root)), 'sha256': item['sha256'],
                      'duration': info['duration'], 'original_id': asset['id'],
                      'original_start_s': item['original_start_s'], 'original_end_s': item['original_end_s']}
            if item['sha256'] in seen:
                duplicates.append(record)
            else:
                seen.add(item['sha256'])
                records.append(record)
    if not records:
        raise ValueError('默认 workspace-data/segments 中没有已保存的完整片段批次。')
    signature = hashlib.sha256(json.dumps(manifests, sort_keys=True).encode()).hexdigest()
    return {'schema_version': 1, 'selection': 'User explicitly selected all saved batches for training',
            'id': 'acane_' + signature[:16], 'manifests': manifests, 'files': records,
            'duplicates': duplicates, 'duration': sum(x['duration'] for x in records)}


def snapshot(library, selection):
    parent = library.root / 'training'
    parent.mkdir(exist_ok=True)
    if not parent.resolve().is_relative_to(library.root):
        raise ValueError('训练目录不能位于资料库之外。')
    final = parent / selection['id']
    if final.exists():
        saved = json.loads((final/'selection.json').read_text(encoding='utf-8'))
        if saved != selection:
            raise ValueError('已有训练快照清单不符。')
        for i, item in enumerate(selection['files']):
            if digest(final/'dataset'/f'{i:05d}.wav') != item['sha256']:
                raise ValueError('已有训练快照被修改。')
        return final
    with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=parent) as temp:
        staging = Path(temp)/'run'
        (staging/'dataset').mkdir(parents=True)
        for i, item in enumerate(selection['files']):
            target = staging/'dataset'/f'{i:05d}.wav'
            shutil.copyfile(library.root/item['source'], target)
            if digest(target) != item['sha256']:
                raise ValueError('复制期间片段发生变化。')
        # Recheck approvals and sources before publishing the immutable selection.
        if scan(library) != selection:
            raise ValueError('复制期间素材或审核发生变化，请重试。')
        (staging/'selection.json').write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding='utf-8')
        staging.rename(final)
    return final


def chunk_frames(frames, rate=40000):
    """Balanced, contiguous ranges: keep the tail instead of dropping it."""
    import math
    if frames < int(.4*rate):
        raise ValueError('片段短于 0.4 秒，无法安全用于当前训练器，请在工作台重新保存。')
    count = max(1, math.ceil(frames/(3*rate)))
    return [(i*frames//count, (i+1)*frames//count) for i in range(count)]

"""Append-only, output-specific human review and versioned WAV exports."""

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .media import MediaError, digest, probe

DECISIONS = ('pending', 'approved', 'redo', 'rejected')
ROLES = ('unknown', 'vocals', 'instrumental', 'other')
SAMPLE_RATES = (16000, 24000, 32000, 40000, 44100, 48000)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class ReviewMixin:
    def _verified_path(self, relative, expected):
        path = (self.root / relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(self.root):
            raise MediaError('记录中的音频路径超出资料库。')
        if not path.is_file():
            raise MediaError(f'音频文件缺失：{relative}')
        if digest(path) != expected:
            raise MediaError(f'音频文件已变化，不能复用此前审核：{relative}')
        return path

    def _review_target(self, job_id, output_path):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None or row['status'] != 'succeeded':
            raise ValueError('只能复核成功任务的具体输出。')
        job = dict(row)
        matches = [o for o in json.loads(job['outputs'] or '[]') if o['path'] == output_path]
        if len(matches) != 1:
            raise ValueError('输出路径必须与该任务记录中的路径完全一致。')
        return job, matches[0]

    def _latest_review(self, job_id, output):
        row = self.db.execute('''SELECT * FROM output_reviews WHERE job_id=?
            AND output_path=? AND output_sha256=? ORDER BY sequence DESC LIMIT 1''',
            (job_id, output['path'], output['sha256'])).fetchone()
        return dict(row) if row else {'sequence': None, 'decision': 'pending', 'role': 'unknown', 'note': ''}

    def review_output(self, job_id, output_path, decision, role='unknown', note=''):
        if decision not in DECISIONS or role not in ROLES:
            raise ValueError('未知审核状态或音轨类型。')
        if decision == 'approved' and role == 'unknown':
            raise ValueError('通过前必须明确音轨类型（例如 vocals 人声）。')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            job, output = self._review_target(job_id, output_path)
            if decision == 'approved':
                asset = self.asset(job['asset_id'])
                self._verified_path(asset['original_path'], asset['id'])
                self._verified_path(output['path'], output['sha256'])
            cursor = self.db.execute('''INSERT INTO output_reviews
                (job_id,output_path,output_sha256,decision,role,note,created_at)
                VALUES (?,?,?,?,?,?,?)''',
                (job_id, output['path'], output['sha256'], decision, role, note, timestamp()))
            result = dict(self.db.execute('SELECT * FROM output_reviews WHERE sequence=?',
                                          (cursor.lastrowid,)).fetchone())
        return result

    def review_history(self, job_id=None):
        sql = 'SELECT * FROM output_reviews'
        params = ()
        if job_id is not None:
            sql += ' WHERE job_id=?'
            params = (job_id,)
        return [dict(r) for r in self.db.execute(sql + ' ORDER BY sequence', params)]

    def review_queue(self):
        results = []
        for row in self.db.execute("SELECT * FROM jobs WHERE status='succeeded' ORDER BY started_at,id"):
            job = dict(row)
            asset = self.asset(job['asset_id'])
            for output in json.loads(job['outputs'] or '[]'):
                review = self._latest_review(job['id'], output)
                try:
                    self._verified_path(output['path'], output['sha256'])
                    integrity, error = 'valid', None
                except (OSError, ValueError) as exc:
                    integrity, error = 'invalid', str(exc)
                results.append({'job_id': job['id'], 'asset_id': asset['id'],
                                'source_filename': asset['filename'], 'source_kind': asset['kind'],
                                'operation': job['operation'], 'parameters': json.loads(job['parameters']),
                                'output': output, 'review': review,
                                'integrity': integrity, 'integrity_error': error})
        return results

    def export_dataset(self, job_ids=None, sample_rate=None, channels=None):
        if sample_rate is not None and (type(sample_rate) is not int or sample_rate not in SAMPLE_RATES):
            raise ValueError('不支持的导出采样率。')
        if channels is not None and (type(channels) is not int or channels not in (1, 2)):
            raise ValueError('导出声道数只能为 1 或 2。')
        requested = set(job_ids) if job_ids is not None else None
        items = [r for r in self.review_queue()
                 if r['review']['decision'] == 'approved' and r['review']['role'] == 'vocals'
                 and (requested is None or r['job_id'] in requested)]
        if not items:
            raise ValueError('没有明确通过的人声结果，未创建数据集。')
        if requested is not None and requested != {r['job_id'] for r in items}:
            raise ValueError('指定任务中有尚未通过的人声结果，未导出。')
        if len({r['asset_id'] for r in items}) != len(items):
            raise ValueError('同一素材有多个通过版本，请用 --job 明确选择一个，避免重复进入数据集。')
        if len({r['output']['sha256'] for r in items}) != len(items):
            raise ValueError('所选人声包含完全重复的音频，请明确选择要导出的版本。')
        # Validate all inputs before allocating an export directory.
        for item in items:
            asset = self.asset(item['asset_id'])
            self._verified_path(asset['original_path'], asset['id'])
            self._verified_path(item['output']['path'], item['output']['sha256'])
        export_id = uuid.uuid4().hex
        parent = self.root / 'datasets'
        parent.mkdir(exist_ok=True)
        if not parent.resolve().is_relative_to(self.root):
            raise ValueError('数据集目录不能链接到资料库外。')
        staging = parent / ('.' + export_id + '.partial')
        staging.mkdir()
        final = parent / export_id
        manifest = {'schema_version': 1, 'id': export_id, 'created_at': timestamp(),
                    'format': 'WAV pcm_f32le', 'sample_rate': sample_rate, 'channels': channels,
                    'selection': 'Explicitly approved vocals; review snapshot at export time.',
                    'processing': 'Whole outputs; no segmentation, EQ, normalization or denoising.',
                    'files': []}
        try:
            for index, item in enumerate(items, 1):
                source = self._verified_path(item['output']['path'], item['output']['sha256'])
                # Freeze the exact reviewed bytes before conversion, including across external edits.
                snapshot = staging / ('input' + source.suffix)
                shutil.copyfile(source, snapshot)
                if digest(snapshot) != item['output']['sha256']:
                    raise MediaError('复核后的音频在导出期间发生变化。')
                original_info = probe(snapshot)
                name = f'{index:04d}_{item["asset_id"][:12]}.wav'
                target = staging / name
                command = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(snapshot),
                           '-map', '0:a:0', '-vn', '-c:a', 'pcm_f32le']
                if sample_rate is not None:
                    command += ['-ar', str(sample_rate)]
                if channels is not None:
                    command += ['-ac', str(channels)]
                subprocess.run(command + [str(target)], check=True, capture_output=True, timeout=600)
                metadata = probe(target)
                if (metadata['sample_rate'] != (sample_rate or original_info['sample_rate'])
                        or metadata['channels'] != (channels or original_info['channels'])
                        or abs(metadata['duration'] - original_info['duration']) > 0.1):
                    raise MediaError('导出 WAV 的时长、声道或采样率与请求不一致。')
                snapshot.unlink()
                asset = self.asset(item['asset_id'])
                sources = [dict(r) for r in self.db.execute('SELECT * FROM sources WHERE asset_id=?', (asset['id'],))]
                manifest['files'].append({**item, 'export_path': name, 'export_sha256': digest(target),
                                          'export_metadata': metadata, 'original': asset, 'sources': sources})
            # Prevent a concurrent review revocation from publishing a stale selection.
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                for item in items:
                    job, output = self._review_target(item['job_id'], item['output']['path'])
                    current = self._latest_review(job['id'], output)
                    if current['sequence'] != item['review']['sequence']:
                        raise ValueError('导出期间审核状态已变化，请重新选择。')
                    self._verified_path(output['path'], item['output']['sha256'])
                    asset = self.asset(item['asset_id'])
                    self._verified_path(asset['original_path'], asset['id'])
                self.write_json(staging / 'manifest.json', manifest)
                staging.rename(final)
            return {'id': export_id, 'directory': str(final), 'count': len(items),
                    'manifest': str(final / 'manifest.json')}
        finally:
            if staging.exists():
                shutil.rmtree(staging)

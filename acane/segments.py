"""Measured audio checks and reversible, human-editable segmentation drafts."""
from array import array
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from .media import MediaError, digest, probe
from .review import timestamp

DEFAULTS = {'silence_db': -45.0, 'min_silence_s': 0.3, 'padding_s': 0.12,
            'max_segment_s': 12.0}


def settings(options=None):
    if options is not None and (not isinstance(options, dict) or set(options)-set(DEFAULTS)):
        raise ValueError('未知切分参数。')
    result = {**DEFAULTS, **(options or {})}
    bounds = {'silence_db': (-90, -10), 'min_silence_s': (0.1, 5),
              'padding_s': (0, 1), 'max_segment_s': (1, 30)}
    for name, value in result.items():
        if type(value) not in (int, float) or not math.isfinite(value) or not bounds[name][0] <= value <= bounds[name][1]:
            raise ValueError('切分参数超出范围：'+name)
    if result['padding_s']*2 >= result['min_silence_s']:
        raise ValueError('两侧保留时长之和必须小于静音间隔。')
    return result


def dbfs(value):
    return 20*math.log10(value) if value > 0 else None


def analyze(source, scratch, options):
    """20 ms RMS across all channels; no downmix, resampling or normalization."""
    info = probe(source)
    raw = scratch/'analysis.f32'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(source),
                    '-map', '0:a:0', '-vn', '-c:a', 'pcm_f32le', '-f', 'f32le', str(raw)],
                   check=True, capture_output=True, timeout=600)
    rate, channels = info['sample_rate'], info['channels']
    window_frames = max(1, round(rate*0.02))
    total_frames, square_sum, peak, near_full, silent_frames = 0, 0.0, 0.0, 0, 0
    quiet_start, intervals = None, []
    threshold = 10**(options['silence_db']/20)
    with raw.open('rb') as stream:
        while block := stream.read(window_frames*channels*4):
            if len(block) % (channels*4):
                raise MediaError('解码音频不完整。')
            values = array('f')
            values.frombytes(block)
            if sys.byteorder != 'little':
                values.byteswap()
            if any(not math.isfinite(x) for x in values):
                raise MediaError('音频含无效数值，不能生成切分草稿。')
            energy = sum(x*x for x in values)
            frames = len(values)//channels
            quiet = math.sqrt(energy/len(values)) < threshold
            if quiet:
                silent_frames += frames
                if quiet_start is None:
                    quiet_start = total_frames/rate
            elif quiet_start is not None:
                intervals.append([quiet_start, total_frames/rate])
                quiet_start = None
            square_sum += energy
            peak = max(peak, max(abs(x) for x in values))
            near_full += sum(abs(x) >= 0.999 for x in values)
            total_frames += frames
    if not total_frames:
        raise MediaError('解码后没有有效采样。')
    duration = total_frames/rate
    if quiet_start is not None:
        intervals.append([quiet_start, duration])
    intervals = [pair for pair in intervals if pair[1]-pair[0]+1e-9 >= options['min_silence_s']]
    count = total_frames*channels
    return {'duration_s': duration, 'sample_rate': rate, 'channels': channels,
            'frames': total_frames, 'window_ms': 1000*window_frames/rate,
            'rms_dbfs': dbfs(math.sqrt(square_sum/count)), 'peak_dbfs': dbfs(peak),
            'near_full_scale_threshold': 0.999, 'near_full_scale_samples': near_full,
            'near_full_scale_ratio': near_full/count, 'quiet_window_ratio': silent_frames/total_frames,
            'silence_intervals': intervals,
            'limitations': '低电平不等于无用声音；接近满幅不等于已证实削波。不检测歌唱、噪声、混响或伴奏残留。'}


def suggest(metrics, options):
    duration, padding = metrics['duration_s'], options['padding_s']
    spans, cursor = [], 0.0
    for start, end in metrics['silence_intervals']:
        if start > cursor:
            spans.append((max(0, cursor-padding), min(duration, start+padding)))
        cursor = end
    if cursor < duration:
        spans.append((max(0, cursor-padding), duration))
    result = []
    for start, end in spans:
        pieces = max(1, math.ceil((end-start)/options['max_segment_s']))
        for index in range(pieces):
            left = start+(end-start)*index/pieces
            right = start+(end-start)*(index+1)/pieces
            warnings = []
            if pieces > 1:
                warnings.append('连续声音超过目标长度，边界可能切断发声，请试听调整。')
            if right-left < 1:
                warnings.append('片段不足 1 秒，请人工判断是否保留。')
            result.append({'start_s': left, 'end_s': right, 'warnings': warnings})
    return result


class SegmentsMixin:
    def _approved_segment_source(self, job_id, output_path, sequence=None):
        job, output = self._review_target(job_id, output_path)
        review = self._latest_review(job_id, output)
        if review['decision'] != 'approved' or review['role'] != 'vocals':
            raise ValueError('请先试听并确认保留这份人声音轨。')
        if sequence is not None and review['sequence'] != sequence:
            raise ValueError('人声审核已变化，请重新生成切分方案。')
        asset = self.asset(job['asset_id'])
        self._verified_path(asset['original_path'], asset['id'])
        source = self._verified_path(output['path'], output['sha256'])
        return job, output, review, asset, source

    def _segments_root(self):
        parent = self.root/'segments'
        parent.mkdir(exist_ok=True)
        if not parent.resolve().is_relative_to(self.root):
            raise ValueError('片段目录不能链接到资料库外。')
        return parent

    def segment_plan(self, job_id, output_path, options=None):
        options = settings(options)
        job, output, review, asset, source = self._approved_segment_source(job_id, output_path)
        parent = self._segments_root()
        with tempfile.TemporaryDirectory(prefix='.analysis-', dir=parent) as directory:
            scratch = Path(directory)
            snapshot = scratch/('source'+source.suffix)
            shutil.copyfile(source, snapshot)
            if digest(snapshot) != output['sha256']:
                raise MediaError('分析期间人声文件发生变化。')
            metrics = analyze(snapshot, scratch, options)
        plan_id = uuid.uuid4().hex
        parameters = json.loads(job['parameters'])
        plan = {'schema_version': 1, 'id': plan_id, 'kind': 'segmentation_plan',
                'created_at': timestamp(), 'job_id': job_id, 'output': output,
                'source_filename': asset['filename'], 'original': asset,
                'sources': [dict(r) for r in self.db.execute('SELECT * FROM sources WHERE asset_id=?', (asset['id'],))],
                'review': review, 'processing_parameters': parameters,
                'original_offset_s': parameters.get('preview_start_s', 0),
                'options': options, 'metrics': metrics, 'segments': suggest(metrics, options),
                'review_status': 'pending', 'training_eligible': False}
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self._approved_segment_source(job_id, output_path, review['sequence'])
            self.write_json(parent/(plan_id+'.json'), plan)
        return plan

    def read_segment_plan(self, plan_id):
        if not isinstance(plan_id, str) or not re.fullmatch('[a-f0-9]{32}', plan_id):
            raise ValueError('切分方案编号无效。')
        path = self._segments_root()/(plan_id+'.json')
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('方案路径超出资料库。')
        plan = json.loads(path.read_text(encoding='utf-8'))
        if plan.get('id') != plan_id or plan.get('kind') != 'segmentation_plan':
            raise ValueError('切分方案格式无效。')
        self._approved_segment_source(plan['job_id'], plan['output']['path'], plan['review']['sequence'])
        return plan

    def render_segments(self, plan_id, intervals=None):
        plan = self.read_segment_plan(plan_id)
        if intervals is None:
            intervals = [{'start_s': x['start_s'], 'end_s': x['end_s']} for x in plan['segments']]
        if not isinstance(intervals, list) or not 1 <= len(intervals) <= 2000:
            raise ValueError('请选择 1 至 2000 个片段；全静音素材不会自动生成片段。')
        rate, duration = plan['metrics']['sample_rate'], plan['metrics']['duration_s']
        frames, previous_end = [], 0
        for pair in intervals:
            if not isinstance(pair, dict) or set(pair) != {'start_s', 'end_s'}:
                raise ValueError('片段必须包含开始和结束时间。')
            start, end = pair['start_s'], pair['end_s']
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in (start, end)):
                raise ValueError('片段时间必须是有限数值。')
            if not 0 <= start < end <= duration+1e-9:
                raise ValueError('片段时间超出音轨范围。')
            left, right = round(start*rate), round(end*rate)
            if left < previous_end or right-left < max(1, round(rate*0.05)):
                raise ValueError('片段必须按顺序排列、不重叠，且不少于 0.05 秒。')
            frames.append((left, right))
            previous_end = right
        _, output, _, _, source = self._approved_segment_source(
            plan['job_id'], plan['output']['path'], plan['review']['sequence'])
        parent = self._segments_root()
        batch_id = uuid.uuid4().hex
        staging, final = parent/('.'+batch_id+'.partial'), parent/batch_id
        staging.mkdir()
        manifest = {'schema_version': 1, 'id': batch_id, 'created_at': timestamp(),
                    'parent_plan': plan, 'review_status': 'pending', 'training_eligible': False,
                    'processing': 'Sample-accurate trim to float32 WAV; no gain, EQ, denoising or resampling.', 'files': []}
        try:
            snapshot = staging/('source'+source.suffix)
            shutil.copyfile(source, snapshot)
            if digest(snapshot) != output['sha256']:
                raise MediaError('切分期间人声文件发生变化。')
            for index, (left, right) in enumerate(frames, 1):
                target = staging/f'{index:04d}.wav'
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(snapshot),
                                '-map', '0:a:0', '-vn', '-af', f'atrim=start_sample={left}:end_sample={right},asetpts=PTS-STARTPTS',
                                '-c:a', 'pcm_f32le', str(target)], check=True, capture_output=True, timeout=600)
                info = probe(target)
                if (info['sample_rate'] != rate or info['channels'] != plan['metrics']['channels']
                        or abs(info['duration']-(right-left)/rate) > 0.002):
                    raise MediaError('切分后采样率、声道或时长不符。')
                manifest['files'].append({'path': target.name, 'sha256': digest(target),
                    'metadata': info, 'start_frame': left, 'end_frame': right,
                    'start_s': left/rate, 'end_s': right/rate,
                    'original_start_s': plan['original_offset_s']+left/rate,
                    'original_end_s': plan['original_offset_s']+right/rate,
                    'review_status': 'pending'})
            snapshot.unlink()
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                self._approved_segment_source(plan['job_id'], plan['output']['path'], plan['review']['sequence'])
                self.write_json(staging/'manifest.json', manifest)
                staging.rename(final)
            return {'id': batch_id, 'count': len(frames), 'directory': str(final),
                    'manifest': str(final/'manifest.json'), 'review_status': 'pending', 'training_eligible': False}
        finally:
            if staging.exists():
                shutil.rmtree(staging)

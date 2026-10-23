from array import array
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import wave

from acane.library import Library
from acane.media import digest, probe
from acane.segments import settings


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class SegmentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = Library(self.root/'library')
        self.source = self.root/'fixture.wav'
        values = array('h', [16384]*8000+[0]*4000+[16384]*8000)
        self.make_source(values)

    def tearDown(self):
        self.library.db.close()
        self.temp.cleanup()

    def make_source(self, values, channels=1):
        if sys.byteorder != 'little':
            values.byteswap()
        with wave.open(str(self.source), 'wb') as stream:
            stream.setparams((channels, 2, 8000, 0, 'NONE', 'uncompressed'))
            stream.writeframes(values.tobytes())
        self.asset = self.library.import_one(self.source, 'singing', 'generated test fixture')['id']
        self.job = uuid.uuid4().hex
        target = self.library.root/'preprocessing'/self.job/'vocals.wav'
        target.parent.mkdir()
        shutil.copyfile(self.source, target)
        self.output = {'path': target.relative_to(self.library.root).as_posix(), 'sha256': digest(target), **probe(target)}
        with self.library.db:
            self.library.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                (self.job,self.asset,'separate_preview',json.dumps({'model':'fixture, not inference','preview_start_s':10}),
                 'succeeded','2026-10-23','2026-10-23',json.dumps([self.output]),None))

    def approve(self, role='vocals'):
        self.library.review_output(self.job,self.output['path'],'approved',role,'test fixture approval')

    def plan(self, options=None):
        return self.library.segment_plan(self.job,self.output['path'],options)

    def test_requires_explicit_vocal_approval(self):
        with self.assertRaisesRegex(ValueError,'保留'):
            self.plan()
        self.approve('instrumental')
        with self.assertRaises(ValueError):
            self.plan()
        self.assertFalse((self.library.root/'segments').exists())

    def test_metrics_known_signal_silence_and_padding(self):
        self.approve()
        plan = self.plan()
        metrics = plan['metrics']
        self.assertAlmostEqual(metrics['peak_dbfs'], 20*math.log10(.5), places=5)
        self.assertAlmostEqual(metrics['rms_dbfs'], 20*math.log10(math.sqrt(.25*.8)), places=5)
        self.assertEqual(metrics['near_full_scale_samples'],0)
        self.assertAlmostEqual(metrics['quiet_window_ratio'],.2)
        self.assertEqual(metrics['silence_intervals'], [[1.0,1.5]])
        self.assertAlmostEqual(plan['segments'][0]['end_s'],1.12)
        self.assertAlmostEqual(plan['segments'][1]['start_s'],1.38)
        self.assertFalse(plan['training_eligible'])
        self.assertEqual(self.library.read_segment_plan(plan['id']),plan)

    def test_opposite_phase_stereo_is_not_misclassified_as_silence(self):
        self.make_source(array('h',[16384,-16384]*8000),channels=2)
        self.approve()
        metrics=self.plan()['metrics']
        self.assertEqual(metrics['quiet_window_ratio'],0)
        self.assertAlmostEqual(metrics['rms_dbfs'],-6.020599913,places=5)

    def test_silence_and_near_full_scale_are_distinct_metrics(self):
        self.make_source(array('h',[0]*8000));self.approve()
        plan=self.plan()
        self.assertIsNone(plan['metrics']['rms_dbfs'])
        self.assertEqual(plan['segments'],[])
        with self.assertRaises(ValueError):self.library.render_segments(plan['id'])
        self.make_source(array('h',[0]*800));self.approve()
        self.assertEqual(self.plan()['segments'],[])
        self.make_source(array('h',[32767]*8000));self.approve()
        self.assertEqual(self.plan()['metrics']['near_full_scale_ratio'],1)

    def test_long_voiced_regions_flag_forced_boundaries(self):
        self.make_source(array('h',[16384]*24000));self.approve()
        plan=self.plan({'max_segment_s':1})
        self.assertEqual(len(plan['segments']),3)
        self.assertTrue(all(x['warnings'] for x in plan['segments']))
        self.assertEqual(plan['segments'][0]['start_s'],0)
        self.assertEqual(plan['segments'][-1]['end_s'],3)

    def test_custom_intervals_preserve_samples_and_provenance(self):
        self.approve();plan=self.plan()
        result=self.library.render_segments(plan['id'],[{'start_s':.25,'end_s':.75}])
        manifest=json.loads(Path(result['manifest']).read_text())
        entry=manifest['files'][0]
        self.assertEqual(entry['start_frame'],2000)
        self.assertEqual(entry['end_frame'],6000)
        self.assertEqual(entry['original_start_s'],10.25)
        self.assertEqual(entry['metadata']['sample_rate'],8000)
        self.assertEqual(entry['metadata']['channels'],1)
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(Path(result['directory'])/entry['path']),'-f','f32le','-'])
        values=array('f');values.frombytes(raw)
        if sys.byteorder!='little':values.byteswap()
        self.assertEqual(len(values),4000)
        self.assertTrue(all(x==.5 for x in values))
        self.assertEqual(manifest['parent_plan']['original']['id'],self.asset)
        self.assertEqual(manifest['parent_plan']['sources'][0]['source_note'],'generated test fixture')
        self.assertEqual(entry['review_status'],'pending')
        self.assertFalse(result['training_eligible'])
        self.assertEqual(digest(self.library.root/self.output['path']),self.output['sha256'])
        again=self.library.render_segments(plan['id'])
        self.assertNotEqual(again['directory'],result['directory'])
        self.assertFalse((self.library.root/'datasets').exists())

    def test_invalid_and_overlapping_intervals_leave_no_output(self):
        self.approve();plan=self.plan()
        invalid=[[],[{'start_s':0,'end_s':float('nan')}],[{'start_s':True,'end_s':1}],
                 [{'start_s':-1,'end_s':1}],[{'start_s':0,'end_s':3}],
                 [{'start_s':0,'end_s':1},{'start_s':.5,'end_s':2}],
                 [{'start_s':0,'end_s':.001}]]
        for intervals in invalid:
            with self.subTest(intervals=intervals),self.assertRaises(ValueError):
                self.library.render_segments(plan['id'],intervals)
        self.assertFalse(any(p.is_dir() for p in (self.library.root/'segments').iterdir()))
        with self.assertRaises(ValueError):self.library.read_segment_plan('../../outside')
        for options in ({'silence_db':float('nan')},{'padding_s':.5},{'max_segment_s':True},{'unknown':1}):
            with self.assertRaises(ValueError):settings(options)

    def test_revoked_review_and_modified_audio_block_saved_plan(self):
        self.approve();plan=self.plan()
        self.library.review_output(self.job,self.output['path'],'redo','vocals')
        with self.assertRaises(ValueError):self.library.render_segments(plan['id'])
        self.approve()
        with self.assertRaisesRegex(ValueError,'变化'):self.library.render_segments(plan['id'])
        plan=self.plan()
        (self.library.root/self.output['path']).write_bytes(b'tampered')
        with self.assertRaises(ValueError):self.library.render_segments(plan['id'])

    def test_concurrent_revocation_removes_partial_batch(self):
        self.approve();plan=self.plan();real_run=subprocess.run
        def revoke(*args,**kwargs):
            result=real_run(*args,**kwargs)
            self.library.review_output(self.job,self.output['path'],'redo','vocals')
            return result
        with patch('acane.segments.subprocess.run',side_effect=revoke),self.assertRaises(ValueError):
            self.library.render_segments(plan['id'])
        self.assertFalse(any(p.is_dir() for p in (self.library.root/'segments').iterdir()))

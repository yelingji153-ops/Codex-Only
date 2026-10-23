import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from acane.library import Library
from acane.workbench import Workbench, MODEL, MODEL_SHA, CONFIG_SHA


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'source.wav'
        with wave.open(str(self.source), 'wb') as stream:
            stream.setparams((1, 2, 22050, 0, 'NONE', 'uncompressed'))
            stream.writeframes(b'\x01\x00'*2205)
        with Library(self.root/'library'):
            pass
        self.app = Workbench(self.root/'library', app_root=self.root)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_upload_preserves_original_and_deduplicates(self):
        first = self.app.import_upload(self.source, '弹唱.wav')
        second = self.app.import_upload(self.source, '另一个名称.wav')
        self.assertEqual(first['id'], second['id'])
        with Library(self.app.root) as library:
            asset = library.asset(first['id'])
            self.assertEqual(asset['filename'], '弹唱.wav')
            self.assertEqual((library.root/asset['original_path']).read_bytes(), self.source.read_bytes())
            sources = [r['path'] for r in library.db.execute('SELECT path FROM sources')]
            self.assertEqual(set(sources), {'upload:弹唱.wav', 'upload:另一个名称.wav'})

    def test_queue_requires_environment_and_verifies_all_assets(self):
        asset = self.app.import_upload(self.source, 'source.wav')['id']
        with self.assertRaisesRegex(ValueError, '环境'):
            self.app.enqueue([asset])
        self.app.environment['ready'] = True
        with self.assertRaises(ValueError):
            self.app.enqueue([asset, 'missing'])
        self.assertEqual(self.app.tasks, [])

    def test_serial_queue_failure_retry_and_gpu_requirement(self):
        asset = self.app.import_upload(self.source, 'source.wav')['id']
        self.app.environment['ready'] = True
        started, release = threading.Event(), threading.Event()
        calls = []

        def separate(*args, **kwargs):
            calls.append(kwargs)
            started.set()
            if not release.wait(5):
                raise RuntimeError('test barrier timed out')
            if len(calls) == 1:
                raise RuntimeError('simulated model failure')
            return {'id': 'fixture-job', 'status': 'succeeded'}

        with patch.object(self.app, '_model_files', return_value=True), \
             patch('acane.workbench.digest', side_effect=lambda p: MODEL_SHA if p.name == MODEL else CONFIG_SHA), \
             patch.object(Library, 'separate', side_effect=separate):
            self.assertEqual(self.app.enqueue([asset])['count'], 1)
            self.assertTrue(started.wait(5))
            self.assertEqual(self.app.enqueue([asset])['count'], 0)
            release.set()
            self.app.executor.submit(lambda: None).result(timeout=10)
            self.assertEqual(self.app.tasks[0]['status'], 'failed')
            self.app.enqueue([asset], force=True)
            self.app.executor.submit(lambda: None).result(timeout=10)
            self.assertEqual(self.app.tasks[1]['status'], 'completed')
            self.assertTrue(all(call['require_cuda'] for call in calls))
            self.assertTrue(calls[1]['force'])

    def test_bad_model_blocks_inference(self):
        asset = self.app.import_upload(self.source, 'source.wav')['id']
        self.app.environment['ready'] = True
        with patch.object(self.app, '_model_files', return_value=True), \
             patch('acane.workbench.digest', return_value='wrong'), \
             patch.object(Library, 'separate') as model:
            self.app.enqueue([asset])
            self.app.executor.submit(lambda: None).result(timeout=10)
            model.assert_not_called()
            self.assertEqual(self.app.tasks[0]['status'], 'failed')

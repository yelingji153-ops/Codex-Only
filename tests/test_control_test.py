import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('control_test',Path(__file__).resolve().parents[1]/'scripts/windows_control/control_test.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ControlTest(unittest.TestCase):
    def sample(self):
        return {'id':m.SAMPLE_ID,'voiceChangerType':'RVC','f0':True,'modelUrl':'https://huggingface.co/example/voices/resolve/main/voice.pth'}

    def test_catalog_requires_exact_candidate_and_pytorch_model(self):
        entry=self.sample();self.assertEqual(m.select_sample({'RVC':[entry]}),entry)
        for catalog in ({'RVC':[]},{'RVC':[entry,entry]},{'RVC':[dict(entry,f0=False)]},{'RVC':[dict(entry,modelUrl=entry['modelUrl']+'.onnx')]}):
            with self.assertRaises(ValueError):m.select_sample(catalog)

    def test_download_origin_and_paths_validated(self):
        self.assertEqual(m.hf_location(self.sample()['modelUrl']),('example/voices','main','voice.pth'))
        for url in ('http://huggingface.co/a/b/resolve/main/x.pth','https://other.example/a/b/resolve/main/x.pth','https://huggingface.co/a/b/resolve/main/../x.pth'):
            with self.assertRaises(ValueError):m.hf_location(url)

    def test_bad_download_never_overwrites_existing_model(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'model.pth';target.write_bytes(b'original')
            response=io.BytesIO(b'broken');response.headers={'Content-Length':'6'}
            with patch.object(m,'urlopen',return_value=response),self.assertRaises(ValueError):
                m.fetch('https://example.invalid',target,hashlib.sha256(b'expected').hexdigest())
            self.assertEqual(target.read_bytes(),b'original')
            self.assertFalse(target.with_suffix('.part').exists())

    def test_verified_cache_never_downloaded_again(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'model.pth';target.write_bytes(b'fixture')
            with patch.object(m,'urlopen',side_effect=AssertionError('unexpected network')):
                m.fetch('https://example.invalid',target,m.sha(target))

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('level',Path(__file__).resolve().parents[1]/'scripts/windows_level/level_training.py')
level=importlib.util.module_from_spec(spec);spec.loader.exec_module(level)

@unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("soundfile"), "Run in audio environment for real WAV checks")
class LevelTests(unittest.TestCase):
    def test_gain_preserves_originals_and_group_dynamics(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'source';src.mkdir();(src/'sliced_audios').mkdir()
            rows=[]
            for name,group,peak in [('0_0_0.wav','00000.wav',1.3),('0_0_1.wav','00000.wav',.5),('0_1_0.wav','00001.wav',.8)]:
                sf.write(src/'sliced_audios'/name,np.full(20000,peak,dtype='float32'),40000,subtype='FLOAT')
                rows.append({'path':name,'source':group})
            (src/'prepared-audio.json').write_text(json.dumps(rows));(src/'model_info.json').write_text('{}')
            before={p.name:level.digest(p) for p in (src/'sliced_audios').iterdir()}
            dst=Path(td)/'new';r=level.prepare(src,dst)
            self.assertEqual(r['attenuated_sources'],1)
            for row in rows:
                a,_=sf.read(src/'sliced_audios'/row['path']);b,_=sf.read(dst/'sliced_audios'/row['path'])
                np.testing.assert_allclose(b,a*r['gains'][row['source']],rtol=1e-6)
                self.assertEqual(before[row['path']],level.digest(src/'sliced_audios'/row['path']))
            self.assertEqual(level.prepare(src,dst),r)
            (dst/'sliced_audios'/'0_0_0.wav').write_bytes(b'changed')
            with self.assertRaises(ValueError):level.prepare(src,dst)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'src';src.mkdir()
            (src/'prepared-audio.json').write_text(json.dumps([{'path':'../escape.wav','source':'x'}]))
            with self.assertRaises(ValueError):level.prepare(src,Path(td)/'out')

    def test_partial_directory_not_overwritten(self):
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'src';(src/'sliced_audios').mkdir(parents=True)
            sf.write(src/'sliced_audios/a.wav',np.ones(20000)*.1,40000,subtype='FLOAT')
            (src/'prepared-audio.json').write_text(json.dumps([{'path':'a.wav','source':'a'}]))
            dst=Path(td)/'out';dst.mkdir();(dst/'keep').write_text('keep')
            with self.assertRaises(ValueError):level.prepare(src,dst)
            self.assertEqual((dst/'keep').read_text(),'keep')

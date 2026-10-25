from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/windows_optimize'))
import activate_model as activation

class ActivationTest(unittest.TestCase):
    def setup_files(self,td):
        root=Path(td);exp=root/'new';old=root/'old';exp.mkdir();old.mkdir()
        (exp/'new_100e_20900s.pth').write_bytes(b'new model')
        (exp/'new.index').write_bytes(b'new index')
        (old/'base_30e_6270s.pth').write_bytes(b'old model')
        (old/'base.index').write_bytes(b'old index')
        return exp,old

    def test_pair_replaced_backup_kept_repeat_safe(self):
        with tempfile.TemporaryDirectory() as td:
            exp,old=self.setup_files(td)
            activation.activate(exp,old,'base');activation.activate(exp,old,'base')
            self.assertEqual((old/'base_30e_6270s.pth').read_bytes(),b'new model')
            self.assertEqual((old/'base.index').read_bytes(),b'new index')
            self.assertEqual((old/'backup-before-opt100/base_30e_6270s.pth').read_bytes(),b'old model')
            self.assertEqual((old/'backup-before-opt100/base.index').read_bytes(),b'old index')

    def test_failed_second_replace_restores_both(self):
        with tempfile.TemporaryDirectory() as td:
            exp,old=self.setup_files(td)
            replace=Path.replace
            def fail(path,target):
                if path.name=='base.index.installing':raise OSError('simulated locked index')
                return replace(path,target)
            with patch.object(Path,'replace',fail):
                with self.assertRaises(OSError):activation.activate(exp,old,'base')
            self.assertEqual((old/'base_30e_6270s.pth').read_bytes(),b'old model')
            self.assertEqual((old/'base.index').read_bytes(),b'old index')
            self.assertFalse((old/'active-model.json').exists())

    def test_missing_new_index_leaves_baseline_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            exp,old=self.setup_files(td);(exp/'new.index').unlink()
            with self.assertRaises(FileNotFoundError):activation.activate(exp,old,'base')
            self.assertEqual((old/'base_30e_6270s.pth').read_bytes(),b'old model')
            self.assertFalse((old/'backup-before-opt100').exists())

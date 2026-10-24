import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('audit',Path(__file__).resolve().parents[1]/'scripts/windows_audit/training_audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class AuditTest(unittest.TestCase):
    def test_nested_and_partial_overlap_counted_once_per_source(self):
        rows=[{'original_id':'a','original_start_s':a,'original_end_s':b} for a,b in [(0,5),(1,2),(4,8)]]
        rows.append({'original_id':'b','original_start_s':0,'original_end_s':2})
        result=m.overlap_summary(rows)
        self.assertEqual(result['summed_source_seconds'],12)
        self.assertEqual(result['unique_source_seconds'],10)
        self.assertEqual(result['overlap_excess_seconds'],2)
        self.assertEqual(result['source_count'],2)

    def test_invalid_intervals_rejected(self):
        for end in (float('nan'),float('inf'),-1,0):
            with self.assertRaises(ValueError):
                m.overlap_summary([{'original_id':'x','original_start_s':0,'original_end_s':end}])

    def test_missing_pretrain_messages_are_unknown_not_failure(self):
        evidence=m.log_evidence("Loaded checkpoint 'G.pth' (epoch 30)")
        self.assertEqual(evidence['initial_pretrained_load_status'],'unknown_no_complete_log_evidence')
        self.assertEqual(evidence['resume'][0]['epoch'],30)

    def test_loading_messages_not_claimed_success_if_later_error(self):
        evidence=m.log_evidence("Loaded pretrained (G) 'x'\nLoaded pretrained (D) 'y'\nThe parameters of the pretrain model do not match")
        self.assertEqual(evidence['initial_pretrained_load_status'],'messages_present_not_proof_of_success')
        self.assertEqual(len(evidence['pretrained_mismatch']),1)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):m.inside(Path(directory),'../outside.npy')

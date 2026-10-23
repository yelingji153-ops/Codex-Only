import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_segments as fixtures
from acane.training_data import scan, snapshot


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class TrainingDataTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SegmentsTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.approve()
        self.library = self.fixture.library
        plan = self.fixture.plan()
        self.batch = self.library.render_segments(plan['id'], [{'start_s':0,'end_s':1}])

    def test_all_batches_deduplicate_preserve_provenance_and_reuse(self):
        plan = self.fixture.plan()
        self.library.render_segments(plan['id'], [{'start_s':0,'end_s':1}])
        selected = scan(self.library)
        self.assertEqual(len(selected['files']), 1)
        self.assertEqual(len(selected['duplicates']), 1)
        self.assertEqual(len(selected['manifests']), 2)
        folder = snapshot(self.library, selected)
        self.assertEqual(folder, snapshot(self.library, scan(self.library)))
        self.assertEqual(selected['files'][0]['original_id'], self.fixture.asset)
        self.assertEqual(selected['files'][0]['original_start_s'], 10)
        original = json.loads(Path(self.batch['manifest']).read_text())
        self.assertFalse(original['training_eligible'])
        self.assertEqual(original['review_status'], 'pending')
        (folder/'dataset/00000.wav').write_bytes(b'broken')
        with self.assertRaises(ValueError):
            snapshot(self.library, selected)

    def test_revoked_vocals_block_training(self):
        self.library.review_output(self.fixture.job, self.fixture.output['path'], 'redo', 'vocals')
        with self.assertRaises(ValueError):
            scan(self.library)

    def test_partial_batches_ignored_but_modified_files_block(self):
        partial = self.library.root/'segments/.incomplete'
        partial.mkdir()
        (partial/'manifest.json').write_text('bad json')
        self.assertEqual(len(scan(self.library)['files']), 1)
        (Path(self.batch['directory'])/'0001.wav').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            scan(self.library)

    def test_manifest_path_escape_blocked(self):
        path = Path(self.batch['manifest'])
        data = json.loads(path.read_text())
        data['files'][0]['path'] = '../../outside.wav'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            scan(self.library)

    def test_copy_race_never_publishes(self):
        selected = scan(self.library)
        with patch('acane.training_data.scan', side_effect=ValueError('revoked during copy')):
            with self.assertRaises(ValueError):
                snapshot(self.library, selected)
        self.assertEqual(list((self.library.root/'training').iterdir()), [])


class ChunkTest(unittest.TestCase):
    def test_tails_and_short_clips_are_not_silently_dropped(self):
        from acane.training_data import chunk_frames
        for frames in (16000, 80000, 120000, 120001, 250000):
            chunks = chunk_frames(frames)
            self.assertEqual(chunks[0][0], 0)
            self.assertEqual(chunks[-1][1], frames)
            self.assertEqual(sum(b-a for a,b in chunks), frames)
            self.assertTrue(all(16000 <= b-a <= 120000 for a,b in chunks))
            self.assertTrue(all(a[1] == b[0] for a,b in zip(chunks, chunks[1:])))
        with self.assertRaises(ValueError):
            chunk_frames(1000)

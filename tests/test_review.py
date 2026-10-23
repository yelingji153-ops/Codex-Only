import csv
import io
import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from acane.cli import main
from acane.library import Library
from acane.media import MediaError, digest, probe


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = Library(self.root / 'library')
        self.asset, self.job, self.output = self.make_result(440)

    def tearDown(self):
        self.library.db.close()
        self.temp.cleanup()

    def make_result(self, frequency, asset=None):
        if asset is None:
            source = self.root / f'{frequency}.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            f'sine=frequency={frequency}:duration=0.2', str(source)], check=True)
            asset = self.library.import_one(source, 'singing', 'fixture provenance')['id']
        job = uuid.uuid4().hex
        path = self.library.root / 'preprocessing' / job / 'audio.wav'
        path.parent.mkdir()
        archived = self.library.root / self.library.asset(asset)['original_path']
        shutil.copyfile(archived, path)
        output = {'path':path.relative_to(self.library.root).as_posix(), 'sha256':digest(path), **probe(path)}
        with self.library.db:
            self.library.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                (job,asset,'separate',json.dumps({'model':'fixture; not real separation'}),
                 'succeeded','2026-10-23','2026-10-23',json.dumps([output]),None))
        return asset, job, output

    def approve(self, job=None, output=None, role='vocals'):
        return self.library.review_output(job or self.job, (output or self.output)['path'],
                                          'approved', role, 'human test fixture decision')

    def test_pending_never_exports_and_approval_requires_explicit_role(self):
        self.assertEqual(self.library.review_queue()[0]['review']['decision'], 'pending')
        with self.assertRaises(ValueError):
            self.library.export_dataset()
        with self.assertRaises(ValueError):
            self.library.review_output(self.job, self.output['path'], 'approved')
        self.assertFalse((self.library.root / 'datasets').exists())

    def test_only_approved_vocals_export_and_snapshot_records_provenance(self):
        rejected = self.make_result(660)
        instrumental = self.make_result(880)
        self.make_result(1000)  # Pending.
        self.approve()
        self.library.review_output(rejected[1], rejected[2]['path'], 'rejected', note='residue')
        self.approve(instrumental[1], instrumental[2], role='instrumental')
        before = digest(self.library.root / self.output['path'])
        result = self.library.export_dataset(sample_rate=24000, channels=1)
        self.assertEqual(result['count'], 1)
        manifest = json.loads(Path(result['manifest']).read_text())
        item = manifest['files'][0]
        wave = Path(result['directory']) / item['export_path']
        self.assertEqual(item['export_metadata']['sample_rate'], 24000)
        self.assertEqual(item['export_metadata']['channels'], 1)
        self.assertEqual(item['original']['id'], self.asset)
        self.assertEqual(item['sources'][0]['source_note'], 'fixture provenance')
        self.assertEqual(item['output']['sha256'], before)
        self.assertEqual(digest(wave), item['export_sha256'])
        self.assertEqual(digest(self.library.root / self.output['path']), before)
        # Revocation affects future selection, not already published snapshots.
        self.library.review_output(self.job, self.output['path'], 'redo', note='reconsidered')
        with self.assertRaises(ValueError):
            self.library.export_dataset()
        self.assertTrue(wave.exists())

    def test_approval_does_not_transfer_to_another_job_or_changed_hash(self):
        self.approve()
        other = self.make_result(440, asset=self.asset)
        queue = {r['job_id']:r for r in self.library.review_queue()}
        self.assertEqual(queue[other[1]]['review']['decision'], 'pending')
        changed = {**self.output,'sha256':'0'*64}
        with self.library.db:
            self.library.db.execute('UPDATE jobs SET outputs=? WHERE id=?', (json.dumps([changed]),self.job))
        queue = {r['job_id']:r for r in self.library.review_queue()}
        self.assertEqual(queue[self.job]['review']['decision'], 'pending')
        with self.assertRaises(ValueError):
            self.library.export_dataset([self.job])

    def test_missing_or_changed_audio_blocks_approval_and_export(self):
        self.approve()
        path = self.library.root / self.output['path']
        path.write_bytes(b'modified')
        self.assertEqual(self.library.review_queue()[0]['integrity'], 'invalid')
        with self.assertRaises(MediaError):
            self.library.export_dataset()
        path.unlink()
        with self.assertRaises(MediaError):
            self.approve()
        # Invalid media can still be rejected with an audit note.
        self.library.review_output(self.job, self.output['path'], 'rejected', note='missing')
        self.assertEqual(len(self.library.review_history()), 2)

    def test_history_is_append_only_persistent_and_csv_safe(self):
        first = self.approve()
        self.library.review_output(self.job, self.output['path'], 'redo', note='=formula')
        with Library(self.library.root) as reopened:
            history = reopened.review_history(self.job)
            self.assertEqual([r['decision'] for r in history], ['approved','redo'])
            self.assertEqual(history[0]['sequence'], first['sequence'])
        with (self.library.report()/'output_reviews.csv').open(encoding='utf-8-sig') as f:
            self.assertEqual(list(csv.DictReader(f))[-1]['note'], "'=formula")

    def test_duplicate_versions_require_explicit_selection(self):
        self.approve()
        other = self.make_result(440, asset=self.asset)
        self.approve(other[1], other[2])
        with self.assertRaisesRegex(ValueError, '多个通过版本'):
            self.library.export_dataset()
        self.assertEqual(self.library.export_dataset([other[1]])['count'], 1)
        with self.assertRaises(ValueError):
            self.library.export_dataset([other[1], 'nonexistent'])

    def test_failed_conversion_leaves_no_dataset_and_no_modified_original(self):
        self.approve()
        before = digest(self.library.root / self.output['path'])
        real_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == 'ffmpeg':
                raise subprocess.CalledProcessError(1, command, stderr='fixture failure')
            return real_run(command, **kwargs)
        with patch('acane.review.subprocess.run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                self.library.export_dataset()
        self.assertEqual(list((self.library.root / 'datasets').iterdir()), [])
        self.assertEqual(digest(self.library.root / self.output['path']), before)

    def test_concurrent_revocation_prevents_publication(self):
        self.approve()
        real_run = subprocess.run
        revoked = False
        def run(command, **kwargs):
            nonlocal revoked
            result = real_run(command, **kwargs)
            if command[0] == 'ffmpeg' and not revoked:
                revoked = True
                with Library(self.library.root) as other:
                    other.review_output(self.job, self.output['path'], 'rejected')
            return result
        with patch('acane.review.subprocess.run', side_effect=run):
            with self.assertRaisesRegex(ValueError, '审核状态已变化'):
                self.library.export_dataset()
        self.assertEqual(list((self.library.root / 'datasets').iterdir()), [])

    def test_migration_keeps_v1_data_and_creates_readable_backup(self):
        self.library.db.execute('DROP TABLE output_reviews')
        self.library.db.execute('PRAGMA user_version=1')
        self.library.db.commit()
        with Library(self.library.root) as upgraded:
            self.assertEqual(upgraded.asset(self.asset)['id'], self.asset)
            self.assertEqual(upgraded.db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(upgraded.review_history(), [])
        backups = list((self.library.root/'reports').glob('schema-v1-*.sqlite3'))
        self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as old:
            self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertEqual(old.execute('SELECT id FROM assets').fetchone()[0],self.asset)

    def test_cli_review_history_and_export(self):
        args = ['--library',str(self.library.root)]
        with redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(args+['review','--job',self.job,'--output',self.output['path'],
                                       '--decision','approved','--role','vocals','--note','test']),0)
            self.assertEqual(json.loads(stream.getvalue())['decision'],'approved')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args+['review-list']),0)
            self.assertEqual(main(args+['review-history','--job',self.job]),0)
            self.assertEqual(main(args+['export','--job',self.job,'--channels','1']),0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(args+['export','--job','missing']),1)

    def test_output_outside_library_cannot_be_approved(self):
        external = self.root/'external.wav'
        shutil.copyfile(self.library.root/self.output['path'],external)
        output = {**self.output,'path':str(external)}
        with self.library.db:
            self.library.db.execute('UPDATE jobs SET outputs=? WHERE id=?',(json.dumps([output]),self.job))
        with self.assertRaises(MediaError):
            self.approve(output=output)

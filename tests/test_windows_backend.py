import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts.windows_backend.prepare_and_preview import download, preview, offline_arguments


class DownloadIntegrityTest(unittest.TestCase):
    def test_offline_never_downloads_missing_files(self):
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'Offline bundle file missing'):
                download('https://example.test/model', Path(folder)/'model', '0'*64, offline=True)
            network.assert_not_called()

    def test_offline_wheel_integrity_and_no_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'wheelhouse').mkdir()
            wheel = root/'wheelhouse/example.whl'
            wheel.write_bytes(b'wheel fixture')
            (root/'offline-wheels.json').write_text(json.dumps({'wheels': [
                {'filename': wheel.name, 'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest()}]}))
            with patch('scripts.windows_backend.prepare_and_preview.BASE', root):
                self.assertIn('--no-index', offline_arguments())
                wheel.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'damaged'):
                    offline_arguments()

    def test_complete_download_is_verified_and_cached_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source', root / 'target'
            source.write_bytes(b'verified model bytes')
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            download(source.as_uri(), target, expected)
            source.unlink()
            download(source.as_uri(), target, expected)
            self.assertEqual(target.read_bytes(), b'verified model bytes')

    def test_hash_failure_never_promotes_partial_or_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source', root / 'target'
            source.write_bytes(b'bad download')
            with self.assertRaisesRegex(ValueError, 'Download hash mismatch'):
                download(source.as_uri(), target, '0' * 64)
            self.assertFalse(target.exists())
            target.write_bytes(b'existing file')
            with self.assertRaisesRegex(ValueError, 'Existing file hash mismatch'):
                download(source.as_uri(), target, '0' * 64)
            self.assertEqual(target.read_bytes(), b'existing file')

    def test_preview_refuses_cpu_fallback_before_model_download(self):
        torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
        modules = {'torch': torch, 'numpy': types.ModuleType('numpy'),
                   'soundfile': types.ModuleType('soundfile'),
                   'audio_separator': types.ModuleType('audio_separator'),
                   'audio_separator.separator': types.SimpleNamespace(Separator=object)}
        with patch.dict('sys.modules', modules):
            with self.assertRaisesRegex(RuntimeError, 'refusing to silently run'):
                preview({})

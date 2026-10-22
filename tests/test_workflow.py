import csv
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from acane.cli import main
from acane.library import Library
from acane.media import MediaError, digest, probe


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "sources"
        self.source.mkdir()
        self.audio = self.source / "测试音频.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=0.3", str(self.audio)], check=True)
        self.library = Library(self.root / "library")

    def tearDown(self):
        self.library.db.close()
        self.temp.cleanup()

    def test_import_preserves_bytes_and_metadata(self):
        before = digest(self.audio)
        result = self.library.import_one(self.audio, "singing", "test provenance")
        asset = self.library.asset(result["id"])
        self.assertEqual(digest(self.audio), before)
        self.assertEqual(digest(self.library.root / asset["original_path"]), before)
        self.assertAlmostEqual(asset["duration"], 0.3, places=2)
        self.assertEqual(asset["sample_rate"], 44100)
        self.assertEqual(asset["review"], "pending")
        self.assertEqual(asset["kind"], "singing")

    def test_duplicate_and_repeat_import_are_idempotent(self):
        other = self.source / "copy.wav"
        shutil.copyfile(self.audio, other)
        self.library.import_batch([self.source])
        again = self.library.import_batch([self.source])
        self.assertEqual([item["status"] for item in again], ["duplicate", "duplicate"])
        self.assertEqual(len(self.library.assets()), 1)
        self.assertEqual(self.library.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        report = self.library.report()
        with (report / "duplicates.csv").open(encoding="utf-8-sig") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 2)

    def test_invalid_media_does_not_stop_batch(self):
        (self.source / "bad.mp3").write_text("invalid")
        results = self.library.import_batch([self.source])
        self.assertEqual(sorted(item["status"] for item in results), ["failed", "imported"])
        self.assertEqual(len(list((self.library.root / "originals").iterdir())), 1)
        self.assertTrue(list((self.library.root / "reports").glob("import-*.json")))

    def test_missing_file_records_failure(self):
        results = self.library.import_batch([self.source / "missing.wav"])
        self.assertEqual(results[0]["status"], "failed")

    def test_reopen_retains_data(self):
        item = self.library.import_one(self.audio)
        with Library(self.library.root) as reopened:
            self.assertEqual(reopened.asset(item["id"])["filename"], self.audio.name)

    def test_archive_tampering_never_overwrites_original(self):
        item = self.library.import_one(self.audio)
        archived = self.library.root / self.library.asset(item["id"])["original_path"]
        archived.write_bytes(b"tampered")
        with self.assertRaises(MediaError):
            self.library.import_one(self.audio)
        self.assertEqual(archived.read_bytes(), b"tampered")
        self.assertNotEqual(self.audio.read_bytes(), b"tampered")

    def test_nested_library_is_excluded_from_discovery(self):
        self.library.import_one(self.audio)
        self.assertEqual(list(self.library.discover([self.root])), [self.audio])
        with self.assertRaises(ValueError):
            list(self.library.discover([self.library.root]))

    def test_flac_mp3_and_video_audio(self):
        for extension in (".flac", ".mp3", ".mkv"):
            path = self.source / f"converted{extension}"
            if extension == ".mkv":
                command = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=16x16:d=0.3",
                           "-i", str(self.audio), "-map", "0:v", "-map", "1:a", "-c:v", "ffv1",
                           "-c:a", "pcm_s16le", "-shortest", str(path)]
            else:
                command = ["ffmpeg", "-v", "error", "-i", str(self.audio), str(path)]
            subprocess.run(command, check=True)
            item = self.library.import_one(path)
            self.assertGreater(self.library.asset(item["id"])["duration"], 0)
            if extension == ".mkv":
                self.assertEqual(self.library.asset(item["id"])["audio_stream"], 1)

    def test_library_copy_uses_portable_relative_paths(self):
        item = self.library.import_one(self.audio)
        destination = self.root / "moved-library"
        shutil.copytree(self.library.root, destination)
        with Library(destination) as moved:
            asset = moved.asset(item["id"])
            self.assertFalse(Path(asset["original_path"]).is_absolute())
            self.assertEqual(digest(moved.root / asset["original_path"]), item["id"])

    def test_video_without_audio_is_rejected(self):
        path = self.source / "silent-video.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "color=black:s=16x16:d=0.1", "-c:v", "ffv1", str(path)], check=True)
        with self.assertRaises(MediaError):
            probe(path)

    def test_csv_formula_is_escaped(self):
        self.library.import_one(self.audio, source_note="=HYPERLINK(1)")
        report = self.library.report()
        with (report / "sources.csv").open(encoding="utf-8-sig") as stream:
            self.assertEqual(next(csv.DictReader(stream))["source_note"], "'=HYPERLINK(1)")

    def test_cli_failed_batch_and_empty_batch_return_nonzero(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--library", str(self.library.root), "import", str(self.source / "missing")]), 1)
            empty = self.root / "empty"
            empty.mkdir()
            self.assertEqual(main(["--library", str(self.library.root), "import", str(empty)]), 1)

    def test_separation_cache_and_rerun_after_missing_output(self):
        # Contract test only: fake worker output is not a separation quality test.
        item = self.library.import_one(self.audio)
        real_run = subprocess.run

        def run(command, **kwargs):
            if len(command) > 1 and command[1] == "-c":
                return subprocess.CompletedProcess(command, 0, stdout="test-version\n")
            if len(command) > 1 and command[1].endswith("worker.py"):
                output = Path(command[3]) / "vocals.wav"
                shutil.copyfile(command[2], output)
                Path(command[-1]).write_text(json.dumps([str(output)]), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with patch("acane.library.subprocess.run", side_effect=run):
            first = self.library.separate(item["id"], "test.onnx")
            self.assertEqual(first["status"], "succeeded")
            self.assertEqual(self.library.separate(item["id"], "test.onnx")["status"], "cached")
            (self.library.root / first["outputs"][0]["path"]).unlink()
            second = self.library.separate(item["id"], "test.onnx")
            self.assertEqual(second["status"], "succeeded")
            self.assertNotEqual(first["id"], second["id"])

    def test_failed_worker_is_recorded_and_can_be_retried(self):
        item = self.library.import_one(self.audio)
        real_run = subprocess.run

        def run(command, **kwargs):
            if len(command) > 1 and command[1] == "-c":
                return subprocess.CompletedProcess(command, 0, stdout="test-version\n")
            if len(command) > 1 and command[1].endswith("worker.py"):
                raise subprocess.TimeoutExpired(command, 1)
            return real_run(command, **kwargs)

        with patch("acane.library.subprocess.run", side_effect=run):
            for _ in range(2):
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.library.separate(item["id"], "test.onnx", timeout=1)
        statuses = [row[0] for row in self.library.db.execute("SELECT status FROM jobs")]
        self.assertEqual(statuses, ["failed", "failed"])


if __name__ == "__main__":
    unittest.main()

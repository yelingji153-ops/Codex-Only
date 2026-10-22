import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from acane import worker


class WorkerContractTest(unittest.TestCase):
    def test_options_reach_backend_and_manifest_uses_output_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest = directory / "outputs.json"
            params = {"segment_size": 256, "override_model_segment_size": True, "overlap": 2, "batch_size": 1}
            separator = Mock()
            separator.separate.return_value = ["vocals.wav"]
            constructor = Mock(return_value=separator)
            module = types.ModuleType("audio_separator.separator")
            module.Separator = constructor
            argv = ["worker.py", "source.wav", str(directory), "models", "test.ckpt", str(manifest), json.dumps(params)]
            with patch.dict(sys.modules, {"audio_separator": types.ModuleType("audio_separator"), "audio_separator.separator": module}), patch.object(sys, "argv", argv):
                worker.main()
            constructor.assert_called_once_with(output_dir=str(directory), model_file_dir="models", output_format="WAV", mdxc_params=params)
            separator.load_model.assert_called_once_with(model_filename="test.ckpt")
            self.assertEqual(json.loads(manifest.read_text()), [str(directory / "vocals.wav")])

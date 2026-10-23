import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('training_launcher', Path(__file__).resolve().parents[1]/'scripts/windows_training/start_training.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class TrainingLauncherTest(unittest.TestCase):
    def test_interactive_installer_inherits_console_and_keeps_failure(self):
        for code in (0, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                process = MagicMock()
                process.__enter__.return_value = process
                process.wait.return_value = code
                process.poll.return_value = code
                with patch.object(launcher.subprocess, 'Popen', return_value=process) as popen:
                    if code:
                        with self.assertRaises(RuntimeError):
                            launcher.run(['fixture'], Path(directory)/'log', interactive=True)
                    else:
                        launcher.run(['fixture'], Path(directory)/'log', interactive=True)
                    self.assertIsNone(popen.call_args.kwargs['stdout'])
                    self.assertFalse(process.stdout.__iter__.called)

    def test_noninteractive_model_output_still_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            process = MagicMock()
            process.__enter__.return_value = process
            process.stdout = iter(['epoch=1\n'])
            process.wait.return_value = 0
            log = Path(directory)/'log'
            with patch.object(launcher.subprocess, 'Popen', return_value=process):
                launcher.run(['fixture'], log)
            self.assertIn('epoch=1', log.read_text())

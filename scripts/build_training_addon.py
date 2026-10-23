"""Small add-on: source only; runtime/model downloads happen on user's PC."""
import hashlib
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [(p, 'training-addon/'+str(p.relative_to(ROOT))) for p in sorted((ROOT/'acane').glob('*.py'))]
    files += [(ROOT/'scripts/windows_training'/name, 'training-addon/'+name)
              for name in ('start_training.py', 'verify_training.py', 'prepare_audio.py', 'download_progress.ps1')]
    files += [(ROOT/'scripts/windows_training/Start_Training.cmd', 'Start_Training.cmd'),
              (ROOT/'scripts/windows_training/Show_Download_Progress.cmd', 'Show_Download_Progress.cmd'),
              (ROOT/'docs/local-training.md', '训练使用说明.md')]
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for source, name in files:
            data = source.read_bytes()
            if name.endswith('.cmd'):
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            bundle.writestr(name, data)
    with zipfile.ZipFile(output) as bundle:
        assert bundle.testzip() is None
    sha = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{sha}  {output.name}\n')
    print(output, output.stat().st_size, sha)


if __name__ == '__main__':
    build(Path(sys.argv[1]))

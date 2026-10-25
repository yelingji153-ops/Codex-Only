from pathlib import Path
import hashlib
import sys
import zipfile
root=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
files={'Start_Level_Training.cmd':'scripts/windows_level/Start_Level_Training.cmd','level-addon/level_training.py':'scripts/windows_level/level_training.py','level-addon/verify_training.py':'scripts/windows_training/verify_training.py','电平对照训练说明.md':'docs/level-training.md'}
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for name,src in files.items():
  data=(root/src).read_bytes()
  if name.endswith('.cmd'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
  z.writestr(name,data)
with zipfile.ZipFile(out) as z:assert z.testzip() is None
out.with_suffix('.zip.sha256').write_text(hashlib.sha256(out.read_bytes()).hexdigest()+'  '+out.name+'\n')
print(out,out.stat().st_size)

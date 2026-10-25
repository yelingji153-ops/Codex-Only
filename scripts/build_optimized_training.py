from pathlib import Path
import hashlib
import sys
import zipfile
root=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
files={'Start_Optimized_100.cmd':'scripts/windows_optimize/Start_Optimized_100.cmd','Compare_100_Models.cmd':'scripts/windows_optimize/Compare_100_Models.cmd','optimize-addon/optimize_training.py':'scripts/windows_optimize/optimize_training.py','optimize-addon/compare_models.py':'scripts/windows_optimize/compare_models.py','optimize-addon/control_helpers.py':'scripts/windows_control/control_test.py','optimize-addon/verify_training.py':'scripts/windows_training/verify_training.py','100轮训练说明.md':'docs/optimized-training.md'}
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for name,src in files.items():
  data=(root/src).read_bytes()
  if name.endswith('.cmd'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
  z.writestr(name,data)
with zipfile.ZipFile(out) as z:assert z.testzip() is None
out.with_suffix('.zip.sha256').write_text(hashlib.sha256(out.read_bytes()).hexdigest()+'  '+out.name+'\n')
print(out,out.stat().st_size)

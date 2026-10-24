from pathlib import Path
import hashlib
import sys
import zipfile
root=Path(__file__).resolve().parents[1];output=Path(sys.argv[1]);output.parent.mkdir(parents=True,exist_ok=True)
files=[(root/'scripts/windows_audit/Check_Training.cmd','Check_Training.cmd'),
       (root/'scripts/windows_audit/training_audit.py','audit-addon/training_audit.py'),
       (root/'scripts/windows_audit/expected-source.json','audit-addon/expected-source.json'),
       (root/'docs/training-audit.md','训练检查说明.md')]
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
 for source,name in files:
  data=source.read_bytes()
  if name.endswith('.cmd'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
  archive.writestr(name,data)
with zipfile.ZipFile(output) as archive:assert archive.testzip() is None
output.with_suffix('.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n')
print(output,output.stat().st_size)

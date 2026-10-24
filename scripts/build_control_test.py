from pathlib import Path
import hashlib
import sys
import zipfile

root=Path(__file__).resolve().parents[1]
output=Path(sys.argv[1]);output.parent.mkdir(parents=True,exist_ok=True)
files=[(root/'scripts/windows_control/Start_Control_Test.cmd','Start_Control_Test.cmd'),
       (root/'scripts/windows_control/control_test.py','control-addon/control_test.py'),
       (root/'scripts/windows_control/settings.json','control-addon/settings.json'),
       (root/'docs/control-test.md','对照测试说明.md')]
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
 for p,name in files:
  data=p.read_bytes()
  if name.endswith('.cmd'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
  archive.writestr(name,data)
with zipfile.ZipFile(output) as archive:assert archive.testzip() is None
output.with_suffix('.zip.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n')
print(output,output.stat().st_size)

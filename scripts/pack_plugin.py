"""Package source only; never imports plugin code or exports installed user data."""
import sys,io,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from plugin_tools import inspect_package
root=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve();data=io.BytesIO()
with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(root.rglob('*')):
        if '__pycache__' in file.parts or file==output:continue
        if file.is_symlink():raise ValueError('不能打包链接')
        if file.is_file():archive.write(file,file.relative_to(root).as_posix())
inspect_package(data.getvalue());output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(data.getvalue());print(output)

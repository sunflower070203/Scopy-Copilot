"""Build a portable GUI plus separate official MCP bridge on Windows."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_paths import APP_VERSION


def run_packager(name,entry,extra):
    args=[sys.executable,"-m","PyInstaller","--noconfirm","--noupx","--onedir","--name",name,
          "--distpath",str(ROOT/"build"/"frozen"),"--workpath",str(ROOT/"build"/"work"/name),
          "--specpath",str(ROOT/"build"/"specs"),*extra,str(ROOT/entry)]
    subprocess.run(args,cwd=ROOT,check=True)


def copy_licenses(target):
    target.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for dist in metadata.distributions():
        name=dist.metadata.get("Name","unknown")
        manifest.append({"name":name,"version":dist.version,"license":dist.metadata.get("License-Expression") or dist.metadata.get("License","")})
        for item in dist.files or []:
            if any(part.lower().startswith(("license","copying","notice")) for part in item.parts) and ".dist-info" in str(item):
                source=Path(dist.locate_file(item))
                if source.is_file():
                    dest=target/name/Path(*item.parts[1:]);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    for name in ("LICENSE.txt","LICENSE"):
        source=Path(sys.base_prefix)/name
        if source.is_file():shutil.copy2(source,target/("Python-"+name))
    (target/"dependencies.json").write_text(json.dumps(sorted(manifest,key=lambda x:x["name"].lower()),ensure_ascii=False,indent=2),encoding="utf-8")


def main():
    if os.name!="nt":raise SystemExit("Build on Windows for Windows")
    release_name=f"Scopy-Copilot-{APP_VERSION}-Windows-x64"
    target=ROOT/"dist"/release_name
    if target.exists():raise SystemExit("Release directory exists; choose a new version or inspect it before rebuilding")
    run_packager("Scopy-Copilot","app_entry.py",["--windowed"])
    vendor=ROOT/"vendor"/"scopy-mcp-server"
    run_packager("Scopy-MCP-Bridge","bridge_entry.py",[
        "--console","--paths",str(vendor),"--collect-all","mcp","--copy-metadata","mcp",
        "--collect-data","jsonschema_specifications","--hidden-import","win32timezone",
        "--add-data",str(vendor/"scopy_mcp_server"/"scopy_api.json")+":scopy_mcp_server"])
    shutil.copytree(ROOT/"build"/"frozen"/"Scopy-Copilot",target)
    shutil.copytree(ROOT/"build"/"frozen"/"Scopy-MCP-Bridge",target/"bridge")
    shutil.copy2(ROOT/"README.md",target/"README.md")
    shutil.copy2(ROOT/"THIRD_PARTY_NOTICES.md",target/"THIRD_PARTY_NOTICES.md")
    (target/"docs").mkdir(exist_ok=True)
    if (ROOT/"docs"/"release-verification.md").is_file():
        shutil.copy2(ROOT/"docs"/"release-verification.md",target/"docs"/"release-verification.md")
    if (ROOT/"requirements-build.lock.txt").is_file():
        shutil.copy2(ROOT/"requirements-build.lock.txt",target/"requirements-build.lock.txt")
    shutil.copytree(vendor,target/"third-party-source"/"scopy-mcp-server",ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
    copy_licenses(target/"licenses")
    (target/"BUILD-INFO.json").write_text(json.dumps({"version":APP_VERSION,"python":sys.version.split()[0],
        "architecture":"Windows x64","pyinstaller":metadata.version("pyinstaller"),
        "scopy_bridge_ref":"v2.2.1","hardware_writes_enabled":False},indent=2),encoding="utf-8")
    archive=ROOT/"dist"/(release_name+".zip")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for path in sorted(target.rglob("*")):
            if path.is_file():z.write(path,Path(release_name)/path.relative_to(target))
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT/"dist"/"SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n",encoding="utf-8")
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    print(json.dumps({"archive":archive.name,"bytes":archive.stat().st_size,"sha256":digest}),flush=True)


if __name__=="__main__":main()

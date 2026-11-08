"""Verify an extracted release without using Python from PATH.

The default is offline only. --real-readonly additionally attaches to the current
Scopy through the frozen official bridge, without enabling any hardware output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_paths import APP_VERSION


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--real-readonly",action="store_true");args=parser.parse_args()
    name=f"Scopy-Copilot-{APP_VERSION}-Windows-x64"
    archive=ROOT/"dist"/(name+".zip")
    acceptance=ROOT/"build"/("acceptance-"+uuid.uuid4().hex[:8]);acceptance.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        if any(n.startswith(("/","\\")) or ".." in Path(n).parts for n in z.namelist()):raise ValueError("Unsafe archive member")
        z.extractall(acceptance)
    app=acceptance/name/"Scopy-Copilot.exe"
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ("KEY","TOKEN","SECRET","PYTHONPATH","PYTHONHOME"))}
    env["PATH"]=str(Path(os.environ["SystemRoot"])/"System32")
    env["LOCALAPPDATA"]=str(acceptance/"profile")
    profile=Path(env["LOCALAPPDATA"])/"ScopyCopilot"/"data"
    result=subprocess.run([str(app),"--self-test"],cwd=acceptance,env=env,timeout=60,capture_output=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if result.returncode:raise RuntimeError("Frozen offline self-test failed; inspect acceptance profile")
    report=json.loads((profile/"self-test.json").read_text(encoding="utf-8"))
    assert report["frozen"] and report["tk_created"]
    assert report["simulation"]["verdict"]=="PASS" and report["simulation"]["source"]=="simulated"
    assert report["bridge_inventory"]["tool_count"]>0
    assert not report["external_api_called"] and report["hardware_write_calls"]==0
    for folder in (profile/"runs").iterdir():
        manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
        assert all(hashlib.sha256((folder/file).read_bytes()).hexdigest()==digest for file,digest in manifest["sha256"].items())
    summary={"version":APP_VERSION,"archive_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
             "frozen_gui":True,"tk_created":True,"python_on_path":False,"user_data_outside_bundle":True,
             "simulation":report["simulation"],"bridge_tool_count":report["bridge_inventory"]["tool_count"],
             "raw_data_hashes_valid":True,"external_api_called":False,"hardware_write_calls":0}
    if args.real_readonly:
        result=subprocess.run([str(app),"--probe-readonly"],cwd=acceptance,env=env,timeout=60,capture_output=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        actual=json.loads((profile/"readonly-check.json").read_text(encoding="utf-8"))
        if result.returncode or not actual["connected"]:raise RuntimeError("Frozen real readonly check did not connect")
        summary["real_scopy_readonly_connected"]=True
        summary["readonly_fields"]=sorted(actual["snapshot"])
    assert not (acceptance/name/"data").exists()
    (ROOT/"docs"/"portable-verification.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=True,indent=2),flush=True)


if __name__=="__main__":main()

"""Install the official v2.2.1 bridge in a project-local optional virtualenv."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
REF = "v2.2.1"
BASE = f"https://raw.githubusercontent.com/analogdevicesinc/scopy/{REF}/tools/scopy-mcp-server/"
FILES = ["pyproject.toml", "README.md", "scopy_mcp_server/__init__.py",
         "scopy_mcp_server/server.py", "scopy_mcp_server/bridge.py", "scopy_mcp_server/scopy_api.json"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    target = ROOT/"vendor"/"scopy-mcp-server"
    hashes = {}
    for name in FILES:
        with urllib.request.urlopen(BASE+name, timeout=30) as response:
            payload = response.read(2_000_000)
        path = target/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
        print("Downloaded", name, flush=True)
    with urllib.request.urlopen(f"https://raw.githubusercontent.com/analogdevicesinc/scopy/{REF}/LICENSE",timeout=30) as response:
        (target/"LICENSE").write_bytes(response.read())
    (target/"provenance.json").write_text(json.dumps({"repository":"https://github.com/analogdevicesinc/scopy", "ref":REF, "sha256":hashes}, indent=2),encoding="utf-8")
    if not args.download_only:
        env = ROOT/".venv-scopy"
        venv.EnvBuilder(with_pip=True).create(env)
        python = env/("Scripts/python.exe" if sys.platform=="win32" else "bin/python")
        # Official minimum, with a local major-version ceiling. Never install globally.
        packages = ["mcp[cli]>=1.10.0,<2"] + (["pywin32>=306"] if sys.platform=="win32" else [])
        subprocess.run([str(python),"-m","pip","install",*packages],check=True)
        with (ROOT/"docs"/"scopy-dependencies.txt").open("w",encoding="utf-8") as f:
            subprocess.run([str(python),"-m","pip","freeze"],stdout=f,check=True)
        print("Official bridge prepared. Scopy settings and hardware were not changed.")


if __name__ == "__main__":
    main()

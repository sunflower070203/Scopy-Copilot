"""Resource, executable and writable data locations for source and frozen builds."""
import os
from pathlib import Path
import sys

APP_VERSION="0.3.0"


def is_frozen():
    return bool(getattr(sys,"frozen",False))


def bundle_root():
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))


def default_data_dir():
    if not is_frozen():return bundle_root()/"data"
    local=os.environ.get("LOCALAPPDATA")
    base=Path(local) if local else Path.home()/"AppData"/"Local"
    return base/"ScopyCopilot"/"data"


def bundled_bridge_path():
    return Path(sys.executable).parent/"bridge"/"Scopy-MCP-Bridge.exe"

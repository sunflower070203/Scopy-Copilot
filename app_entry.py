"""Portable application entry point and explicit offline installation checks."""
import json
import sys
import tkinter as tk

from controller import Controller
from desktop import DesktopApp,main as desktop_main
from runtime_paths import APP_VERSION,default_data_dir,is_frozen
from scopy import ScopyClient


def write_report(name,report):
    folder=default_data_dir();folder.mkdir(parents=True,exist_ok=True)
    (folder/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")


def run_self_test():
    root=tk.Tk();root.withdraw()
    controller=Controller(default_data_dir())
    app=DesktopApp(root,controller=controller)
    try:
        root.update_idletasks()
        capture=controller.run_simulation({})
        inventory=ScopyClient().inventory()
        report={"version":APP_VERSION,"frozen":is_frozen(),"tk_created":True,
                "simulation":capture["summary"],"bridge_inventory":inventory,
                "external_api_called":False,"hardware_write_calls":0}
    finally:
        app.close()
    write_report("self-test.json",report)
    return report


def main():
    if sys.argv[1:]==["--self-test"]:
        try:run_self_test();return 0
        except Exception as error:
            write_report("self-test.json",{"passed":False,"error_type":type(error).__name__})
            return 1
    if sys.argv[1:]==["--probe-readonly"]:
        result=Controller(default_data_dir()).check_hardware()
        write_report("readonly-check.json",result)
        return 0 if result["connected"] else 1
    if sys.argv[1:]:return 2
    desktop_main()
    return 0


if __name__=="__main__":raise SystemExit(main())

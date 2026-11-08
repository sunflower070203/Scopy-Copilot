Option Explicit
Dim fs, sh, base, python
Set fs = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fs.GetParentFolderName(WScript.ScriptFullName)
python = fs.BuildPath(base, ".venv-scopy\Scripts\pythonw.exe")
sh.CurrentDirectory = base
If fs.FileExists(python) Then
  sh.Run """" & python & """ """ & fs.BuildPath(base, "desktop.py") & """", 0, False
Else
  sh.Run "pyw -3 """ & fs.BuildPath(base, "desktop.py") & """", 0, False
End If

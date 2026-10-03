Option Explicit
Dim shell, fs, root, python, home
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
home = shell.ExpandEnvironmentStrings("%USERPROFILE%")
If fs.FileExists(root & "\JobArchive.exe") Then
  shell.Run Chr(34) & root & "\JobArchive.exe" & Chr(34), 1, False
  WScript.Quit 0
End If
python = home & "\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
If Not fs.FileExists(python) Then python = home & "\AppData\Local\Programs\Python\Python314\python.exe"
If Not fs.FileExists(python) Then
  MsgBox "Python 3.12+ is required. See README.md.", 48, "JobArchive"
  WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & root & "\server.py" & Chr(34) & " --open", 0, False

' install_sync_silent.vbs - runs install_sync_windows.ps1 elevated and hidden.
'
' Double-click to install: the UAC prompt still appears (by design), but the
' PowerShell console stays hidden and the output goes to install_sync.log.
' Arguments are forwarded to the installer, for example: -Source repo -Force

Option Explicit

Dim shell, fso, here, script, logPath, command, index, extra

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)
script = here & "\install_sync_windows.ps1"
logPath = here & "\install_sync.log"

If Not fso.FileExists(script) Then
    MsgBox "install_sync_windows.ps1 not found next to this launcher.", 16, "cmk-sync"
    WScript.Quit 1
End If

extra = ""
For index = 0 To WScript.Arguments.Count - 1
    extra = extra & " " & WScript.Arguments(index)
Next

command = "-NoProfile -ExecutionPolicy Bypass -Command ""& '" & script & "'" _
    & extra & " *> '" & logPath & "'"""

shell.ShellExecute "powershell.exe", command, "", "runas", 0

MsgBox "Installation started. See:" & vbCrLf & logPath, 64, "cmk-sync"

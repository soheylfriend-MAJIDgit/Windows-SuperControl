' Windows SuperControl - no-console launcher
' ---------------------------------------------------------------
' This script runs bootstrap.py with a HIDDEN window (Run style 0).
' No black cmd.exe window appears at all. Double-click this file,
' or use setup_shortcut.vbs to put a shortcut on your Desktop.
' ---------------------------------------------------------------
Option Explicit

Dim fso, sh, here, scriptFile, dataRoot, flagFile, logFile, tmpFile
Dim candidates, i, cmd, py, started, msg

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

here        = fso.GetParentFolderName(WScript.ScriptFullName)
scriptFile  = fso.BuildPath(here, "bootstrap.py")
dataRoot    = sh.ExpandEnvironmentStrings("%APPDATA%")
If dataRoot = "" Or InStr(dataRoot, "%") > 0 Then
    dataRoot = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\AppData\Roaming"
End If
dataRoot    = fso.BuildPath(dataRoot, "WindowsSuperControl")
flagFile    = fso.BuildPath(dataRoot, "started.flag")
logFile     = fso.BuildPath(dataRoot, "launch.log")
tmpFile     = fso.BuildPath(sh.ExpandEnvironmentStrings("%TEMP%"), "wsc_which.txt")

If Not fso.FileExists(scriptFile) Then
    MsgBox "فایل bootstrap.py کنار run.vbs پیدا نشد." & vbCrLf & scriptFile, _
           16, "Windows SuperControl"
    WScript.Quit 1
End If

If Not fso.FolderExists(dataRoot) Then fso.CreateFolder dataRoot
On Error Resume Next
If fso.FileExists(flagFile) Then fso.DeleteFile flagFile, True
If fso.FileExists(tmpFile)  Then fso.DeleteFile tmpFile, True
On Error Goto 0

' --- find a Python interpreter without ever showing a console ---
Function Which(exeName)
    Dim rc, text, line
    Which = ""
    On Error Resume Next
    rc = sh.Run("cmd.exe /c where " & exeName & " > """ & tmpFile & """ 2>&1", 0, True)
    If fso.FileExists(tmpFile) Then
        Set text = fso.OpenTextFile(tmpFile, 1, False)
        If Not text.AtEndOfStream Then line = Trim(text.ReadLine)
        text.Close
        fso.DeleteFile tmpFile, True
        If InStr(LCase(line), LCase(exeName)) > 0 And InStr(line, "\") > 0 Then Which = line
    End If
    On Error Goto 0
End Function

Dim q
q = """"
ReDim candidates(7)
candidates(0) = Which("pyw.exe")
candidates(1) = Which("pythonw.exe")
candidates(2) = Which("python.exe")
candidates(3) = Which("py.exe")
' fall back to the usual per-user install locations
Dim base, folder, guess
base = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
If fso.FolderExists(base) Then
    For Each folder In fso.GetFolder(base).SubFolders
        guess = fso.BuildPath(folder.Path, "pythonw.exe")
        If fso.FileExists(guess) Then
            candidates(4) = guess
            Exit For
        End If
    Next
End If
If fso.FileExists("C:\Python311\pythonw.exe") Then candidates(5) = "C:\Python311\pythonw.exe"
If fso.FileExists("C:\Python312\pythonw.exe") Then candidates(6) = "C:\Python312\pythonw.exe"
If fso.FileExists("C:\Python313\pythonw.exe") Then candidates(7) = "C:\Python313\pythonw.exe"

started = False
For i = 0 To UBound(candidates)
    py = candidates(i)
    If py <> "" Then
        If InStr(LCase(fso.GetFileName(py)), "pyw") > 0 Or _
           InStr(LCase(fso.GetFileName(py)), "pythonw") > 0 Then
            If LCase(fso.GetFileName(py)) = "pyw.exe" Then
                cmd = q & py & q & " -3 " & q & scriptFile & q
            Else
                cmd = q & py & q & " " & q & scriptFile & q
            End If
        Else
            ' py.exe / python.exe are console apps, but Run(...,0,...) hides them
            If LCase(fso.GetFileName(py)) = "py.exe" Then
                cmd = q & py & q & " -3 " & q & scriptFile & q
            Else
                cmd = q & py & q & " " & q & scriptFile & q
            End If
        End If
        On Error Resume Next
        Err.Clear
        sh.Run cmd, 0, False
        If Err.Number = 0 Then
            WScript.Sleep 2200
            If fso.FileExists(flagFile) Then
                started = True
                Exit For
            End If
        End If
        Err.Clear
        On Error Goto 0
    End If
Next

If Not started Then
    msg = "پایتون پیدا نشد یا برنامه اجرا نشد." & vbCrLf & vbCrLf & _
          "۱) Python 3.9+ را از python.org نصب کن (تیک Add to PATH)." & vbCrLf & _
          "۲) سپس دوباره run.vbs را اجرا کن." & vbCrLf & vbCrLf
    If fso.FileExists(logFile) Then
        msg = msg & "لاگ کامل:" & vbCrLf & logFile
    End If
    MsgBox msg, 16, "Windows SuperControl - خطای اجرا"
    WScript.Quit 1
End If

WScript.Quit 0

' Creates a desktop shortcut named "Windows SuperControl" that starts
' run.vbs with wscript.exe -> no black console window, ever.
Option Explicit
Dim fso, sh, here, desktop, lnkPath, oLink
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
here    = fso.GetParentFolderName(WScript.ScriptFullName)
desktop = sh.SpecialFolders("Desktop")
lnkPath = fso.BuildPath(desktop, "Windows SuperControl.lnk")

Set oLink = sh.CreateShortcut(lnkPath)
oLink.TargetPath       = "wscript.exe"
oLink.Arguments        = "//B //Nologo """ & fso.BuildPath(here, "run.vbs") & """"
oLink.WorkingDirectory = here
oLink.Description      = "Windows SuperControl - پایش و اجرای کدهای درایو"
oLink.IconLocation     = "%SystemRoot%\System32\shell32.dll,167"
oLink.WindowStyle      = 7   ' minimized (wscript has no window anyway)
oLink.Save

MsgBox "شورتکات «Windows SuperControl» روی دسکتاپ ساخته شد." & vbCrLf & vbCrLf & _
       "از این به بعد فقط روی آن دوبار کلیک کن؛ هیچ پنجرهٔ مشکی باز نمیشود.", _
       64, "Windows SuperControl"

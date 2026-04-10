Set objArgs = WScript.Arguments
If objArgs.Count < 2 Then WScript.Quit
Set objShell = CreateObject("WScript.Shell")
strArgs = ""
' Skip first arg (the python exe) and second arg (the script path) to handle them specially if needed
' But actually, we just want to rebuild the full command line from all args
For i = 0 to objArgs.Count - 1
    arg = objArgs(i)
    ' Escape quotes in the argument
    arg = Replace(arg, """", """""")
    strArgs = strArgs & """" & arg & """ "
Next
' Run with 0 = Hidden, False = Don't wait for return
objShell.Run strArgs, 0, False

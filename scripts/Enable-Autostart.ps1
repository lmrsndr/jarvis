$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'Start-Jarvis.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File "' + $launcher + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'Jarvis Command Center' -Action $action -Trigger $trigger -Settings $settings -Description 'Start the local Jarvis server after owner sign-in.'

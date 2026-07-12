param(
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [string]$EnvFile = ".env.demo"
)

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$runnerScript = Join-Path $workspacePath "deploy\windows\run-runner.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`" -Workspace `"$workspacePath`" -Python `"$Python`" -EnvFile `"$EnvFile`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $workspacePath
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "astock-runner" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "astock P4 observation runner"

param(
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [string]$EnvFile = ".env.demo"
)

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$env:PYTHONPATH = Join-Path $workspacePath "src"
Set-Location -LiteralPath $workspacePath
& $Python -m astock.cli runner --env-file (Join-Path $workspacePath $EnvFile)
exit $LASTEXITCODE

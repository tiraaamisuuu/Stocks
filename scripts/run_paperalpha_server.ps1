param(
    [double]$BudgetGbp = 150,
    [string]$DashboardUrl = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$notificationConfig = Join-Path $projectRoot "state\notifications.json"
$logDirectory = Join-Path $projectRoot "state"
$logPath = Join-Path $logDirectory "paperalpha-server.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

if (-not (Test-Path -LiteralPath $python)) {
    throw "The PaperAlpha environment is missing. Run scripts\install_windows_server.ps1 first."
}
if (-not (Test-Path -LiteralPath $notificationConfig)) {
    throw "The notification configuration is missing. Run scripts\install_windows_server.ps1 first."
}
$budgetArgument = $BudgetGbp.ToString([System.Globalization.CultureInfo]::InvariantCulture)

$runnerArguments = @(
    "-m", "paperalpha.day_trader",
    "--budget-gbp", $budgetArgument,
    "--fractional",
    "--continuous",
    "--interval", "60",
    "--dashboard-url", $DashboardUrl
)

Push-Location $projectRoot
try {
    "[$(Get-Date -Format o)] Starting PaperAlpha with a GBP $BudgetGbp paper budget." | Add-Content -LiteralPath $logPath
    & $python @runnerArguments *>> $logPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

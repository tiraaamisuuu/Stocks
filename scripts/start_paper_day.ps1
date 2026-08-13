param(
    [double]$Budget = 0,
    [double]$BudgetGbp = 0,
    [switch]$Fractional,
    [switch]$NoNews,
    [string]$DashboardUrl = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$notificationConfig = Join-Path $projectRoot "state\notifications.json"

Push-Location $projectRoot
try {
    if ($Budget -gt 0 -and $BudgetGbp -gt 0) {
        throw "Use either -Budget (USD) or -BudgetGbp, not both."
    }
    if ($Budget -le 0 -and $BudgetGbp -le 0) {
        $Budget = 1000
    }

    python -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        throw "PaperAlpha installation failed."
    }

    if (-not (Test-Path -LiteralPath $notificationConfig)) {
        python -m paperalpha.notifications setup
        if ($LASTEXITCODE -ne 0) {
            throw "Notification setup failed."
        }
        Write-Host ""
        Write-Host "Install ntfy on the iPhone and subscribe to the topic printed above."
        Read-Host "Press Enter after the subscription is visible on the phone"
    }

    python -m paperalpha.notifications test
    if ($LASTEXITCODE -ne 0) {
        throw "The test notification failed."
    }

    $runnerArguments = @(
        "-m", "paperalpha.day_trader",
        "--dashboard-url", $DashboardUrl
    )
    if ($BudgetGbp -gt 0) {
        $runnerArguments += @("--budget-gbp", $BudgetGbp)
    }
    else {
        $runnerArguments += @("--budget", $Budget)
    }
    if ($Fractional) {
        $runnerArguments += "--fractional"
    }
    if ($NoNews) {
        $runnerArguments += "--no-news"
    }

    Write-Host "PaperAlpha will remain in this window until today's closing report is complete."
    python @runnerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "The paper-day runner stopped with an error."
    }
}
finally {
    Pop-Location
}

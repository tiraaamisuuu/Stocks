param(
    [double]$BudgetGbp = 150,
    [string]$TaskName = "PaperAlpha Server",
    [string]$DashboardUrl = ""
)

$ErrorActionPreference = "Stop"
if ($BudgetGbp -le 0) {
    throw "-BudgetGbp must be positive."
}
if ($DashboardUrl -match '[\r\n"]') {
    throw "-DashboardUrl cannot contain quotes or newlines."
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$notificationConfig = Join-Path $projectRoot "state\notifications.json"
$runnerScript = Join-Path $projectRoot "scripts\run_paperalpha_server.ps1"
$systemPowerShell = Join-Path $PSHOME "powershell.exe"
$budgetArgument = $BudgetGbp.ToString([System.Globalization.CultureInfo]::InvariantCulture)

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the PaperAlpha Python environment."
        }
    }

    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        throw "PaperAlpha installation failed."
    }

    if (-not (Test-Path -LiteralPath $notificationConfig)) {
        & $venvPython -m paperalpha.notifications setup
        if ($LASTEXITCODE -ne 0) {
            throw "Notification setup failed."
        }
        Write-Host ""
        Write-Host "Install ntfy on the iPhone and subscribe to the topic printed above."
        Read-Host "Press Enter after the topic is subscribed on the phone"
    }

    & $venvPython -m paperalpha.notifications test
    if ($LASTEXITCODE -ne 0) {
        throw "The ntfy test notification failed."
    }

    $actionArguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden",
        "-File", ('"{0}"' -f $runnerScript),
        "-BudgetGbp", $budgetArgument,
        "-DashboardUrl", ('"{0}"' -f $DashboardUrl)
    ) -join " "
    $action = New-ScheduledTaskAction -Execute $systemPowerShell -Argument $actionArguments -WorkingDirectory $projectRoot
    $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $triggers = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $userId),
        (New-ScheduledTaskTrigger -Daily -At "12:00")
    )
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew `
        -RestartCount 10 `
        -RestartInterval (New-TimeSpan -Minutes 5) `
        -StartWhenAvailable

    $task = New-ScheduledTask -Action $action -Trigger $triggers -Principal $principal -Settings $settings `
        -Description "PaperAlpha continuous paper-trading alerts with a GBP $BudgetGbp budget."
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $existingTask) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName

    Write-Host ""
    Write-Host "PaperAlpha server installed and started."
    Write-Host "Task:   $TaskName"
    Write-Host "Budget: GBP $BudgetGbp (converted to USD at each paper entry)"
    Write-Host "Log:    $projectRoot\state\paperalpha-server.log"
    Write-Host "The Windows account must stay signed in; locking the screen is fine."
}
finally {
    Pop-Location
}

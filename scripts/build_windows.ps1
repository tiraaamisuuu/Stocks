$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $projectRoot
try {
    python -m pip install -e ".[build]"
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }

    python -m PyInstaller --noconfirm --clean PaperAlpha.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    $executable = Join-Path $projectRoot "dist\PaperAlpha.exe"
    if (-not (Test-Path -LiteralPath $executable)) {
        throw "Expected executable was not created: $executable"
    }

    $file = Get-Item -LiteralPath $executable
    $hash = Get-FileHash -LiteralPath $executable -Algorithm SHA256
    Write-Output "Built $($file.FullName)"
    Write-Output "Size: $([math]::Round($file.Length / 1MB, 2)) MB"
    Write-Output "SHA256: $($hash.Hash)"
}
finally {
    Pop-Location
}

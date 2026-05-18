param([Parameter(Mandatory)][string]$PluginId)

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "[conxa] Node.js not found — installing via winget..."
    winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

$NpxCommand = Get-Command npx.cmd -ErrorAction SilentlyContinue
if (-not $NpxCommand) {
    $NpxCommand = Get-Command npx -ErrorAction SilentlyContinue
}

if (-not $NpxCommand) {
    throw "[conxa] npx not found. Install Node.js LTS, then retry."
}

$NpxPath = if ($NpxCommand.Source) { $NpxCommand.Source } else { $NpxCommand.Path }
& $NpxPath -y "@kiran_nandi_123/conxa" install $PluginId

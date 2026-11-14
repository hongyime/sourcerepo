param(
  [string]$Workspace = (Resolve-Path (Join-Path (Join-Path (Join-Path $PSScriptRoot "..") "..") "..")).Path
)

$ErrorActionPreference = "Stop"

$templateDir = Join-Path $PSScriptRoot "bats"
if (-not (Test-Path -LiteralPath $templateDir)) {
  throw "BAT template directory not found: $templateDir"
}

$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$expectedSource = Join-Path $workspacePath "sourcerepo"
if (-not (Test-Path -LiteralPath $expectedSource)) {
  throw "Workspace does not contain sourcerepo: $workspacePath"
}

Get-ChildItem -LiteralPath $templateDir -Filter "*.bat" | Sort-Object Name | ForEach-Object {
  $destination = Join-Path $workspacePath $_.Name
  Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
  Write-Host "Installed $($_.Name) -> $destination"
}

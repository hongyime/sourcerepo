param(
  [string]$Owner = "hongyime",
  [string]$Name = "theprawntemplate",
  [string]$Description = "Compliant starter template for The Prawn Organisation projects.",
  [string]$SourcePath = (Join-Path (Join-Path $PSScriptRoot "templates") "theprawntemplate")
)

$ErrorActionPreference = "Stop"

$shellRoot = Split-Path -Parent $PSScriptRoot
$fullName = "$Owner/$Name"
$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) "theprawntemplate-publish"
$repoPath = Join-Path $workRoot $Name

function Copy-TemplateFiles {
  param(
    [string]$From,
    [string]$To
  )

  Get-ChildItem -LiteralPath $To -Force |
    Where-Object { $_.Name -ne ".git" } |
    Remove-Item -Recurse -Force

  Get-ChildItem -LiteralPath $From -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $To -Recurse -Force
  }
  Copy-Item -LiteralPath (Join-Path $shellRoot "LICENSE") -Destination (Join-Path $To "LICENSE") -Force
  Copy-Item -LiteralPath (Join-Path $shellRoot "NOTICE") -Destination (Join-Path $To "NOTICE") -Force
}

if (-not (Test-Path -LiteralPath $SourcePath)) {
  throw "Template source not found: $SourcePath"
}

Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null

$exists = $true
gh repo view $fullName --json nameWithOwner --jq .nameWithOwner *> $null
if ($LASTEXITCODE -ne 0) {
  $exists = $false
}

if ($exists) {
  gh repo clone $fullName $repoPath
}
else {
  New-Item -ItemType Directory -Force -Path $repoPath | Out-Null
  git -C $repoPath init -b main | Out-Null
}

Copy-TemplateFiles -From $SourcePath -To $repoPath

git -C $repoPath add -A
$changes = git -C $repoPath status --porcelain
if ($changes) {
  git -C $repoPath commit -m "chore: publish project template" | Out-Null
}

if ($exists) {
  if ($changes) {
    git -C $repoPath push | Out-Null
  }
}
else {
  gh repo create $fullName --public --source $repoPath --remote origin --push --description $Description
}

gh api -X PATCH "repos/$fullName" -f "description=$Description" -F is_template=true | Out-Null

Write-Host "Published $fullName as a GitHub template repository."

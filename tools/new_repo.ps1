param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[A-Za-z0-9._-]+$')]
  [string]$Name,

  [ValidateSet("hongyime", "bryanseah234")]
  [string]$Owner = "hongyime",

  [Parameter(Mandatory = $true)]
  [ValidateLength(1, 120)]
  [string]$Description,

  [ValidateSet("standard", "showcase")]
  [string]$Tier = "standard",

  [string]$Homepage = "",

  [Parameter(Mandatory = $true)]
  [ValidateCount(3, 6)]
  [string[]]$Topics,

  [switch]$Private,

  [string]$TemplateRepo = "hongyime/theprawntemplate",

  [switch]$NoTemplate,

  [switch]$SeedState,

  [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

$shellRoot = Split-Path -Parent $PSScriptRoot
$repoPath = Join-Path $RepoRoot $Name
$fullName = "$Owner/$Name"
$useTemplate = -not $NoTemplate

function Read-TopicList {
  param([string]$Path)

  $topics = New-Object System.Collections.Generic.HashSet[string]
  $inTopics = $false
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match '^topics:\s*$') {
      $inTopics = $true
      continue
    }
    if ($line -match '^[A-Za-z_-]+:\s*$') {
      $inTopics = $false
    }
    if ($inTopics -and $line -match '^\s*-\s+(.+?)\s*$') {
      [void]$topics.Add($Matches[1])
    }
  }
  return $topics
}

function Add-YamlListItem {
  param(
    [string]$Path,
    [string]$Section,
    [string]$Value
  )

  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.AddRange([string[]](Get-Content -LiteralPath $Path))
  if ($lines -contains "  - $Value") {
    return
  }

  $insertAt = $lines.Count
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -eq "${Section}:") {
      $insertAt = $i + 1
      while ($insertAt -lt $lines.Count -and $lines[$insertAt] -match '^\s+-\s+') {
        $insertAt++
      }
      break
    }
  }
  $lines.Insert($insertAt, "  - $Value")
  Set-Content -LiteralPath $Path -Value $lines -Encoding UTF8
}

function Add-ReposEntry {
  param(
    [string]$Path,
    [string]$FullName,
    [string]$Description,
    [string]$Homepage,
    [string]$Visibility,
    [string[]]$Topics
  )

  $content = Get-Content -LiteralPath $Path -Raw
  if ($content -match "(?m)^$([regex]::Escape($FullName)):\s*$") {
    throw "$FullName already exists in repos.yml"
  }

  $entry = New-Object System.Collections.Generic.List[string]
  $entry.Add($FullName + ":")
  $entry.Add("  description: $($Description | ConvertTo-Json -Compress)")
  $entry.Add("  homepage: $($Homepage | ConvertTo-Json -Compress)")
  if ($Visibility -eq "private") {
    $entry.Add("  visibility: private")
  }
  $entry.Add("  topics:")
  foreach ($topic in $Topics) {
    $entry.Add("    - $topic")
  }
  Add-Content -LiteralPath $Path -Value ($entry -join [Environment]::NewLine) -Encoding UTF8
}

function Add-GitPathIfExists {
  param(
    [string]$RepoPath,
    [string]$RelativePath
  )

  if (Test-Path -LiteralPath (Join-Path $RepoPath $RelativePath)) {
    git -C $RepoPath add -- $RelativePath
  }
}

if (Test-Path -LiteralPath $repoPath) {
  throw "Path already exists: $repoPath"
}

$allowedTopics = Read-TopicList -Path (Join-Path $shellRoot "topics.yml")
foreach ($topic in $Topics) {
  if (-not $allowedTopics.Contains($topic)) {
    throw "Topic '$topic' is not in topics.yml"
  }
}

if ($Tier -eq "showcase" -and [string]::IsNullOrWhiteSpace($Homepage)) {
  throw "Showcase repos need a real homepage URL"
}

$visibility = if ($Private) { "--private" } else { "--public" }
$visibilityValue = if ($Private) { "private" } else { "public" }

if ($useTemplate) {
  Write-Host "Creating $fullName from template $TemplateRepo..."
  gh repo create $fullName $visibility --template $TemplateRepo --clone $repoPath --description $Description
  if ($LASTEXITCODE -ne 0) {
    throw "Template creation failed. Check that $TemplateRepo exists and is marked as a template repository, or rerun with -NoTemplate."
  }
}
else {
  Write-Host "Creating $fullName from local compliant scaffold..."
  New-Item -ItemType Directory -Path $repoPath | Out-Null
  git -C $repoPath init -b main | Out-Null
}

Copy-Item -LiteralPath (Join-Path $shellRoot "LICENSE") -Destination (Join-Path $repoPath "LICENSE") -Force
Copy-Item -LiteralPath (Join-Path $shellRoot "NOTICE") -Destination (Join-Path $repoPath "NOTICE") -Force

$readme = @"
# $Name

$Description

## What It Does

Describe the concrete workflow before publishing.

## Stack

Document the runtime, framework, and important services.

## Setup

Add setup instructions before publishing.

## Deploy

Add deployment instructions or state that this repo is not deployed.

## License

Apache-2.0. See LICENSE and NOTICE.
"@
Set-Content -LiteralPath (Join-Path $repoPath "README.md") -Value $readme -Encoding UTF8

if (-not (Test-Path -LiteralPath (Join-Path $repoPath ".gitignore"))) {
  $gitignore = @"
.env
.env.*
!.env.example
node_modules/
.venv/
venv/
dist/
build/
.next/
coverage/
__pycache__/
.pytest_cache/
"@
  Set-Content -LiteralPath (Join-Path $repoPath ".gitignore") -Value $gitignore -Encoding UTF8
}

if ($SeedState) {
  $agentsDir = Join-Path $repoPath ".agents"
  New-Item -ItemType Directory -Force -Path $agentsDir | Out-Null
  $stateTemplate = Join-Path (Join-Path $repoPath ".agents") "STATE.template.md"
  $statePath = Join-Path (Join-Path $repoPath ".agents") "STATE.md"
  if (Test-Path -LiteralPath $stateTemplate) {
    Copy-Item -LiteralPath $stateTemplate -Destination $statePath -Force
  }
}

foreach ($path in @("README.md", "LICENSE", "NOTICE", ".gitignore", "AGENTS.md", "CONTRIBUTING.md", ".env.example", ".agents", ".github")) {
  Add-GitPathIfExists -RepoPath $repoPath -RelativePath $path
}
if (-not $useTemplate) {
  git -C $repoPath commit -m "chore: initialise compliant repository" | Out-Null
  gh repo create $fullName $visibility --source $repoPath --remote origin --push --description $Description
}
else {
  $status = git -C $repoPath status --porcelain
  if ($status) {
    git -C $repoPath commit -m "chore: initialise project from template" | Out-Null
    git -C $repoPath push | Out-Null
  }
}

$topicArgs = @()
foreach ($topic in $Topics) {
  $topicArgs += "--add-topic"
  $topicArgs += $topic
}
if ($topicArgs.Count -gt 0) {
  gh repo edit $fullName @topicArgs
}
if (-not [string]::IsNullOrWhiteSpace($Homepage)) {
  gh api -X PATCH "repos/$fullName" -f "homepage=$Homepage" | Out-Null
}

Add-YamlListItem -Path (Join-Path $shellRoot "tiers.yml") -Section $Tier -Value $fullName
Add-ReposEntry -Path (Join-Path $shellRoot "repos.yml") -FullName $fullName -Description $Description -Homepage $Homepage -Visibility $visibilityValue -Topics $Topics

python (Join-Path (Join-Path $shellRoot "tools") "scan_identity.py") $repoPath --quiet
if ($LASTEXITCODE -ne 0) {
  throw "Identity scan failed for $repoPath"
}

python (Join-Path (Join-Path $shellRoot "tools") "check_repo.py") $repoPath --json | Out-Host
if ($LASTEXITCODE -ne 0) {
  throw "Compliance check failed for $repoPath"
}

Write-Host "Created $fullName at $repoPath"
Write-Host "Review and commit the tiers.yml/repos.yml changes in sourcerepo."

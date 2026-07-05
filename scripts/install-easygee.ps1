param(
  [string]$PluginDir = (Join-Path $HOME "plugins\easygee"),
  [string]$MarketplacePath = (Join-Path $HOME ".agents\plugins\marketplace.json"),
  [string]$Repo = "https://github.com/Rimagination/easygee.git",
  [string]$Branch = "main",
  [switch]$SkipPull,
  [switch]$SkipCodexAdd
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "==> $Message"
}

function Ensure-Parent {
  param([string]$Path)
  $parent = Split-Path -Parent $Path
  if ($parent -and -not (Test-Path $parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
  }
}

function Save-Json {
  param(
    [object]$Value,
    [string]$Path
  )
  $json = $Value | ConvertTo-Json -Depth 20
  [System.IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

Write-Step "Installing EasyGEE into $PluginDir"
Ensure-Parent $PluginDir

if (Test-Path $PluginDir) {
  if (Test-Path (Join-Path $PluginDir ".git")) {
    if (-not $SkipPull) {
      Write-Step "Updating existing checkout"
      git -C $PluginDir fetch origin $Branch
      git -C $PluginDir checkout $Branch
      git -C $PluginDir pull --ff-only origin $Branch
    }
  } else {
    throw "Target exists but is not a git checkout: $PluginDir"
  }
} else {
  Write-Step "Cloning $Repo"
  git clone --branch $Branch $Repo $PluginDir
}

$manifest = Join-Path $PluginDir ".codex-plugin\plugin.json"
if (-not (Test-Path $manifest)) {
  throw "Missing Codex plugin manifest: $manifest"
}

Write-Step "Updating personal marketplace"
Ensure-Parent $MarketplacePath
if (Test-Path $MarketplacePath) {
  $marketplace = Get-Content -Raw -Encoding UTF8 $MarketplacePath | ConvertFrom-Json
  if (-not $marketplace.name) {
    $marketplace | Add-Member -NotePropertyName name -NotePropertyValue "local-plugins"
  }
  if (-not $marketplace.interface) {
    $marketplace | Add-Member -NotePropertyName interface -NotePropertyValue ([pscustomobject]@{ displayName = "Local Plugins" })
  }
  if ($null -eq $marketplace.plugins) {
    $marketplace | Add-Member -NotePropertyName plugins -NotePropertyValue @()
  }
} else {
  $marketplace = [pscustomobject]@{
    name = "local-plugins"
    interface = [pscustomobject]@{ displayName = "Local Plugins" }
    plugins = @()
  }
}

$entry = [pscustomobject]@{
  name = "easygee"
  source = [pscustomobject]@{
    source = "local"
    path = "./plugins/easygee"
  }
  policy = [pscustomobject]@{
    installation = "AVAILABLE"
    authentication = "ON_INSTALL"
  }
  category = "Science"
}

$plugins = @($marketplace.plugins)
$existing = $plugins | Where-Object { $_.name -eq "easygee" } | Select-Object -First 1
if ($existing) {
  $existing.source = $entry.source
  $existing.policy = $entry.policy
  $existing.category = $entry.category
} else {
  $marketplace.plugins = @($plugins + $entry)
}
Save-Json $marketplace $MarketplacePath

$validator = Join-Path $HOME ".codex\skills\.system\plugin-creator\scripts\validate_plugin.py"
if (Test-Path $validator) {
  Write-Step "Validating plugin"
  python $validator $PluginDir
} else {
  Write-Warning "Plugin validator not found; checked manifest only."
}

if (-not $SkipCodexAdd) {
  $codex = Get-Command codex -ErrorAction SilentlyContinue
  if ($codex) {
    $marketplaceName = $marketplace.name
    Write-Step "Registering plugin with Codex"
    codex plugin add "easygee@$marketplaceName"
  } else {
    Write-Warning "Codex CLI not found. Marketplace was updated; install from the Codex app or run: codex plugin add easygee@$($marketplace.name)"
  }
}

Write-Step "EasyGEE installation complete"
Write-Host "Plugin: $PluginDir"
Write-Host "Marketplace: $MarketplacePath"

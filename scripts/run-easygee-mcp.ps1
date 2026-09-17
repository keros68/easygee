param()

$ErrorActionPreference = "Stop"

# Codex reads launcher stderr as UTF-8; the console default (e.g. GBK) is not.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$pluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$server = Join-Path $pluginRoot "scripts\easygee_mcp_server.py"

if (-not (Test-Path -LiteralPath $server)) {
  throw "EasyGEE MCP server not found: $server"
}

$python = $env:EASYGEE_PYTHON
if (-not $python) {
  $python = "python"
}

$env:PYTHONIOENCODING = "utf-8"
& $python $server
exit $LASTEXITCODE

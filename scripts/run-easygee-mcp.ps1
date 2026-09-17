param()

$ErrorActionPreference = "Stop"

# Keep launcher diagnostics UTF-8 for MCP clients on localized Windows hosts.
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

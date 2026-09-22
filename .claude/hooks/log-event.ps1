$ErrorActionPreference = 'SilentlyContinue'

try {
  $inputJson = [Console]::In.ReadToEnd()
  $projectDir = $env:CLAUDE_PROJECT_DIR
  if ($projectDir -and $inputJson) {
    $runsDir = Join-Path $projectDir '.os\runs'
    if (-not (Test-Path -LiteralPath $runsDir)) {
      New-Item -ItemType Directory -Path $runsDir -Force | Out-Null
    }
    $file = Join-Path $runsDir ("events-{0}.jsonl" -f (Get-Date -Format 'yyyyMMdd'))
    try {
      $event = $inputJson | ConvertFrom-Json
      $line = [ordered]@{
        ts       = (Get-Date -Format 'o')
        type     = $event.hook_event_name
        tool     = $event.tool_name
        tool_use = ($event.tool_input | ConvertTo-Json -Compress)
        cwd      = $env:CLAUDE_PROJECT_DIR
      } | ConvertTo-Json -Compress
    } catch {
      $line = $inputJson
    }
    Add-Content -LiteralPath $file -Value $line -NoNewline
    [Console]::Error.WriteLine('')
  }
} catch {
  [Console]::Error.WriteLine('')
}
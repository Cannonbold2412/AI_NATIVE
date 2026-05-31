"use strict";

const { execFileSync } = require("child_process");
const path = require("path");

if (process.platform !== "win32") {
  process.exit(0);
}

const rootPattern = path.join(__dirname, "..").replace(/[\\^$.*+?()[\]{}|]/g, "\\$&");

const script = `
$self = ${process.pid}
$all = Get-CimInstance Win32_Process
$roots = $all | Where-Object {
  $_.ProcessId -ne $self -and
  $_.CommandLine -match '${rootPattern}' -and
  (
    $_.CommandLine -match 'renderer\\\\vite\\.config\\.ts' -or
    $_.CommandLine -match 'CONXA_RENDERER_URL=http://localhost:5174' -or
    $_.CommandLine -match 'scripts\\\\dev-electron\\.js' -or
    $_.CommandLine -match 'electron\\\\dist\\\\electron\\.exe' -or
    $_.CommandLine -match 'concurrently.*npm:dev:renderer.*npm:dev:electron'
  ) -and
  $_.Name -notmatch 'pwsh|powershell'
}
$ids = New-Object 'System.Collections.Generic.HashSet[int]'
$queue = New-Object 'System.Collections.Generic.Queue[int]'
foreach ($p in $roots) {
  [void]$ids.Add([int]$p.ProcessId)
  $queue.Enqueue([int]$p.ProcessId)
}
while ($queue.Count -gt 0) {
  $parent = $queue.Dequeue()
  foreach ($child in ($all | Where-Object { $_.ParentProcessId -eq $parent })) {
    if ($child.ProcessId -ne $self -and $ids.Add([int]$child.ProcessId)) {
      $queue.Enqueue([int]$child.ProcessId)
    }
  }
}
foreach ($id in $ids) {
  Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}
`;

try {
  execFileSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], {
    stdio: "ignore",
    windowsHide: true,
  });
} catch {
  // Best effort cleanup only. If this fails, Vite will still report the port conflict.
}

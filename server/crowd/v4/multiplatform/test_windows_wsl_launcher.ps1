# Offline executable tests: powershell -NoProfile -File test_windows_wsl_launcher.ps1
# No WSL/native process, login, network or storage outside a temporary fixture.
param([string]$LauncherPath = (Join-Path $PSScriptRoot 'windows-wsl.ps1'))
$ErrorActionPreference = 'Stop'
$HostExecutable = (Get-Process -Id $PID).Path
$Temporary = Join-Path ([IO.Path]::GetTempPath()) ('crowd-wsl-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Temporary | Out-Null
$Fixture = Join-Path $Temporary 'fixture.ps1'
@'
param([string]$ConfigFile)
$ErrorActionPreference = 'Stop'
$c = Get-Content -Raw $ConfigFile | ConvertFrom-Json
$script:Calls = @()
function wsl.exe {
 $script:Calls += ,@($args)
 $global:LASTEXITCODE = 0
 if ($args[0] -eq '--list') { "  NAME STATE VERSION`n* Ubuntu Stopped 2"; return }
 if ($args -contains 'wslpath') { '/mnt/c/kit with space'; return }
 if ($args -contains '-c') { $c.Home; return }
 $script:Calls | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $c.Output
}
& $c.Launcher -Action $c.Action -LinuxArguments @($c.Arguments)
'@ | Set-Content -Encoding UTF8 $Fixture
function Assert-Equal($Actual, $Expected, $Message) {
 if ((ConvertTo-Json -InputObject $Actual -Depth 8 -Compress) -cne (ConvertTo-Json -InputObject $Expected -Depth 8 -Compress)) { throw $Message }
}
function Run-Case([string]$Name, [string]$Action, [string[]]$Arguments, [string]$FixtureHome, [bool]$Success) {
 $Output = Join-Path $Temporary ($Name + '.output.json')
 $Config = Join-Path $Temporary ($Name + '.input.json')
 @{Launcher = (Resolve-Path $LauncherPath).Path; Action = $Action; Arguments = @($Arguments); Home = $FixtureHome; Output = $Output} | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $Config
 & $HostExecutable -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Fixture -ConfigFile $Config *> (Join-Path $Temporary ($Name + '.log'))
 $Code = $LASTEXITCODE
 if ($Success) {
  if ($Code -ne 0 -or -not (Test-Path $Output)) { throw ($Name + ': launcher failed') }
  return @(Get-Content -Raw $Output | ConvertFrom-Json)
 }
 if ($Code -eq 0 -or (Test-Path $Output)) { throw ($Name + ': unsafe home reached launch') }
 return @()
}
try {
 foreach ($Action in @('install','bind','start','check')) {
  $Calls = @(Run-Case ('default-' + $Action) $Action @('--status') '/home/user with space' $true)
  $Entry = if ($Action -eq 'install') { 'install-linux.sh' } elseif ($Action -eq 'bind') { 'bind-linux.sh' } else { 'start-linux.sh' }
  $Expected = @('--distribution','Ubuntu','--exec','/bin/sh',('/mnt/c/kit with space/' + $Entry))
  if ($Action -eq 'check') { $Expected += '--check' }
  $Expected += @('--root','/home/user with space/.local/share/CrowdWorker','--status')
  Assert-Equal @($Calls[-1]) $Expected ('default-' + $Action + ': root/argv changed')
  if (@($Calls | Where-Object { $_ -contains '-c' }).Count -ne 1) { throw 'default home must be read exactly once' }
 }
 foreach ($Explicit in @(@('--root','/home/existing node','--status'), @('--root=/home/existing node','--status'))) {
  $Calls = @(Run-Case ('explicit-' + $Explicit.Count) 'bind' $Explicit '/invalid/unused' $true)
  Assert-Equal @($Calls[-1]) (@('--distribution','Ubuntu','--exec','/bin/sh','/mnt/c/kit with space/bind-linux.sh') + $Explicit) 'explicit root/argv changed'
  if (@($Calls | Where-Object { $_ -contains '-c' }).Count -ne 0) { throw 'explicit root must not read HOME' }
 }
 $Counter = 0
 foreach ($FixtureHome in @('', '/', '../bad', '/mnt/c/Users/test', "/home/a`n/home/b")) {
  $Counter++
  Run-Case ('bad-home-' + $Counter) 'bind' @('--status') $FixtureHome $false | Out-Null
 }
 'PASS: 11 offline launcher cases; no real WSL call'
} finally {
 Remove-Item -LiteralPath $Temporary -Recurse -Force
}

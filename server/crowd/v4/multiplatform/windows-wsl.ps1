# Requires an already installed WSL2 distribution; never installs/replaces it.
param(
 [ValidateSet('install','start','check')][string]$Action = 'install',
 [string]$Distribution = 'Ubuntu',
 [Parameter(ValueFromRemainingArguments=$true)][string[]]$LinuxArguments
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'existing_wsl2_required' }
$inventory = ((& wsl.exe --list --verbose 2>&1) -join "`n").Replace([string][char]0, '')
if ($LASTEXITCODE -ne 0 -or $inventory -notmatch ('(?m)^\s*\*?\s*' + [regex]::Escape($Distribution) + '\s+\S+\s+2\s*$')) { throw 'existing_wsl2_distribution_required' }
$LinuxDirectory = (& wsl.exe --distribution $Distribution --exec wslpath -a $PSScriptRoot).Trim()
if ($LASTEXITCODE -ne 0 -or -not $LinuxDirectory.StartsWith('/')) { throw 'wsl_package_path_unavailable' }
$Entry = if ($Action -eq 'install') { 'install-linux.sh' } else { 'start-linux.sh' }
if ($Action -eq 'check') { $LinuxArguments = @('--check') + $LinuxArguments }
& wsl.exe --distribution $Distribution --exec /bin/sh "$LinuxDirectory/$Entry" @LinuxArguments
exit $LASTEXITCODE

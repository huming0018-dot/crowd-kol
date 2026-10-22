# Requires an already installed WSL2 distribution; never installs/replaces it.
param(
 [ValidateSet('install','start','check','bind')][string]$Action = 'install',
 [string]$Distribution = 'Ubuntu',
 [Parameter(ValueFromRemainingArguments=$true)][string[]]$LinuxArguments
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'existing_wsl2_required' }
$inventory = ((& wsl.exe --list --verbose 2>&1) -join "`n").Replace([string][char]0, '')
if ($LASTEXITCODE -ne 0 -or $inventory -notmatch ('(?m)^\s*\*?\s*' + [regex]::Escape($Distribution) + '\s+\S+\s+2\s*$')) { throw 'existing_wsl2_distribution_required' }
$LinuxDirectory = (& wsl.exe --distribution $Distribution --exec wslpath -a $PSScriptRoot).Trim()
if ($LASTEXITCODE -ne 0 -or -not $LinuxDirectory.StartsWith('/')) { throw 'wsl_package_path_unavailable' }
# Match install-linux.py's default without asking participants to type a root.
$HasRoot = @($LinuxArguments | Where-Object { $_ -ceq '--root' -or $_ -clike '--root=*' }).Count -gt 0
if (-not $HasRoot) {
 $LinuxHome = ((& wsl.exe --distribution $Distribution --exec /bin/sh -c 'printf "%s\n" "$HOME"' 2>&1) -join "`n").Trim()
 if ($LASTEXITCODE -ne 0 -or -not $LinuxHome.StartsWith('/') -or $LinuxHome -eq '/' -or $LinuxHome.StartsWith('/mnt/') -or $LinuxHome -match '[\x00-\x1f]') { throw 'wsl_private_home_unavailable' }
 $LinuxArguments = @('--root', "$LinuxHome/.local/share/CrowdWorker") + @($LinuxArguments)
}
$Entry = if ($Action -eq 'install') { 'install-linux.sh' } elseif ($Action -eq 'bind') { 'bind-linux.sh' } else { 'start-linux.sh' }
if ($Action -eq 'check') { $LinuxArguments = @('--check') + $LinuxArguments }
& wsl.exe --distribution $Distribution --exec /bin/sh "$LinuxDirectory/$Entry" @LinuxArguments
exit $LASTEXITCODE

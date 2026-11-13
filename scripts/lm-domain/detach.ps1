# Starts one job script as a process that does not belong to the shell that starts it.
#
# The Windows service for management (WMI) creates the process, so the process is not a child of
# the calling shell and is in none of its job objects. A restart of the calling shell or of its
# session leaves the job running. scripts/lm-domain/job.sh wraps the job: it writes the log
# build/lm-domain/logs/NAME.log and the state files build/lm-domain/state/NAME.started and
# NAME.done. A job script must be safe to start again: it skips the work that is already done.
#
# Usage, from any folder:
#   powershell -File scripts/lm-domain/detach.ps1 -Name collect -Where wsl -Script scripts/lm-domain/jobs/collect.sh
#   powershell -File scripts/lm-domain/detach.ps1 -Name train -Where bash -Script scripts/lm-domain/jobs/train.sh
# -Where wsl runs the script in the Ubuntu distribution of WSL, and -Where bash runs it in Git Bash.
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][ValidateSet("wsl", "bash")][string]$Where,
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$Arguments = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not (Test-Path (Join-Path $root $Script))) { throw "the job script $Script does not exist under $root" }
$state = Join-Path $root "build\lm-domain\state"
New-Item -ItemType Directory -Force $state | Out-Null
New-Item -ItemType Directory -Force (Join-Path $root "build\lm-domain\logs") | Out-Null
$started = Join-Path $state "$Name.started"
$done = Join-Path $state "$Name.done"
if ((Test-Path $started) -and -not (Test-Path $done)) {
    $text = Get-Content $started -Raw
    if ($text -match "windows_pid (\d+)") {
        if (Get-Process -Id ([int]$Matches[1]) -ErrorAction SilentlyContinue) {
            throw "the job $Name is still running: $text"
        }
    }
}
if ($Where -eq "wsl") {
    $drive = $root.Substring(0, 1).ToLower()
    $linuxRoot = "/mnt/$drive" + ($root.Substring(2) -replace "\\", "/")
    $commandLine = "wsl.exe -d Ubuntu -- bash $linuxRoot/scripts/lm-domain/job.sh $Name $Script $Arguments"
} else {
    $unixRoot = $root -replace "\\", "/"
    $commandLine = "`"C:\Program Files\Git\bin\bash.exe`" `"$unixRoot/scripts/lm-domain/job.sh`" $Name $Script $Arguments"
}
Remove-Item -Force -ErrorAction SilentlyContinue $done
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $commandLine; CurrentDirectory = $root }
if ($result.ReturnValue -ne 0) { throw "Win32_Process.Create returned $($result.ReturnValue) for: $commandLine" }
$now = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
Set-Content -Path $started -Encoding ascii -Value "started $now windows_pid $($result.ProcessId) command $commandLine"
Write-Output "started $Name as Windows process $($result.ProcessId)"

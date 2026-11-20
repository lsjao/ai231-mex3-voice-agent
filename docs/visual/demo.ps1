# One-click demo launcher (run from the laptop):  powershell -ExecutionPolicy Bypass -File docs\visual\demo.ps1 [-PiIp 192.168.88.8] [-SshTarget rpi]
param([string]$PiIp = "192.168.88.8", [string]$SshTarget = "rpi")
$ErrorActionPreference = "Continue"
$page = (Resolve-Path (Join-Path $PSScriptRoot "index.html")).Path

Write-Host "1/5 Pi reachable at $PiIp ?"
if (-not (Test-Connection -Count 1 -Quiet $PiIp)) { Write-Host "   NO. Same network? New IP? Re-run with -PiIp <ip> -SshTarget jaolacuata@<ip>" -ForegroundColor Red; exit 1 }

Write-Host "2/5 Starting MCP servers on the Pi (idempotent, sets speaker 80%)"
ssh $SshTarget "bash ~/mex3/scripts/start_servers.sh"

Write-Host "3/5 Key and credit check"
ssh $SshTarget "cd ~/mex3 && .venv/bin/python bench/check_keys.py"

Write-Host "4/5 Echo check: STAY SILENT for about a minute"
ssh $SshTarget "bash ~/mex3/scripts/echo_check.sh"

Write-Host "5/5 Opening the visual and starting the agent (new window; it plays a ringtone when ready)"
Start-Process $page
$url = "file:///" + ($page -replace '\','/') + "?host=" + $PiIp + ":8106"
Start-Process $url
Start-Process powershell -ArgumentList "-NoExit","-Command","ssh $SshTarget 'bash ~/mex3/scripts/run_agent.sh'"

Start-Sleep 5
try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://$PiIp`:8106/sessions" | Out-Null; Write-Host "Events server on :8106 is UP. Pill should say LIVE." -ForegroundColor Green }
catch { Write-Host "Events server on :8106 NOT reachable. Visual will stay WAITING; ask the pipeline session how it is started." -ForegroundColor Yellow }

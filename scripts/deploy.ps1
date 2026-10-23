# Deploy from Windows 10/11 to the Raspberry Pi using the built-in OpenSSH client and tar.
#   .\scripts\deploy.ps1 [-Target pi@hcp.local] [-RemoteDir hcp]
# config.json and data/ on the Pi are never overwritten. Host keys are verified by ssh as usual.
param(
  [string]$Target = $(if ($env:HCP_TARGET) { $env:HCP_TARGET } else { "pi@hcp.local" }),
  [string]$RemoteDir = $(if ($env:HCP_DIR) { $env:HCP_DIR } else { "hcp" })
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

foreach ($tool in "ssh", "scp", "tar") {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "$tool not found. Install the 'OpenSSH Client' optional feature (Settings > Apps > Optional features)."
  }
}

$archive = Join-Path $env:TEMP "hcp-deploy.tgz"
Write-Host "==> packing"
tar --exclude=__pycache__ -czf $archive hcp deploy scripts config.example.json README.md docs
if ($LASTEXITCODE -ne 0) { throw "tar failed" }

Write-Host "==> uploading to ${Target}:$RemoteDir"
scp $archive "${Target}:/tmp/hcp-deploy.tgz"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }
ssh $Target "mkdir -p '$RemoteDir' && rm -rf '$RemoteDir/hcp' && tar -xzf /tmp/hcp-deploy.tgz -C '$RemoteDir' && rm /tmp/hcp-deploy.tgz && chmod +x '$RemoteDir'/deploy/*.sh '$RemoteDir'/scripts/*.sh"
if ($LASTEXITCODE -ne 0) { throw "extract failed" }
Remove-Item $archive

ssh $Target "systemctl list-unit-files hcp.service >/dev/null 2>&1"
if ($LASTEXITCODE -eq 0) {
  Write-Host "==> restarting service"
  ssh -t $Target "sudo systemctl restart hcp && sleep 3 && systemctl --no-pager status hcp | head -5"
} else {
  Write-Host "==> first deployment: finish setup on the Pi with"
  Write-Host "    ssh -t $Target 'cd $RemoteDir && sudo ./deploy/install.sh'"
}

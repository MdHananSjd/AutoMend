# AutoMend — Demo Environment Reset Script for PowerShell (Person A)
$ErrorActionPreference = "Continue"

$TARGET_URL = if ($env:TARGET_URL) { $env:TARGET_URL } else { "http://localhost:8000" }
$WATCHER_URL = if ($env:WATCHER_URL) { $env:WATCHER_URL } else { "http://localhost:8080" }

Write-Host "=== 1. Resetting Target Service Failure Injection State ===" -ForegroundColor Green
Invoke-RestMethod -Uri "${TARGET_URL}/debug/reset" -Method Post

Write-Host "=== 2. Resetting Watcher Cooldown State ===" -ForegroundColor Green
Invoke-RestMethod -Uri "${WATCHER_URL}/reset" -Method Post

Write-Host "=== 3. Verifying Target Service Health ===" -ForegroundColor Green
$health = Invoke-RestMethod -Uri "${TARGET_URL}/health" -Method Get
Write-Host "Target Health: $($health | ConvertTo-Json -Compress)" -ForegroundColor Yellow

Write-Host "=== Demo Environment Reset Complete ===" -ForegroundColor Green

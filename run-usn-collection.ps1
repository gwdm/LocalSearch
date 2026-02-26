# Run USN Journal Collection (Host → Docker)
# This extracts the PowerShell script from Docker and runs it on Windows host

Write-Host "Extracting USN collection script from Docker..." -ForegroundColor Cyan

# Extract the latest script from Docker container
docker cp localsearch-app:/app/extract-and-collect.ps1 ./extract-and-collect.ps1

Write-Host "Running USN collection on Windows host..." -ForegroundColor Green
& .\extract-and-collect.ps1

Write-Host "`nUSN journal updated! Changes written to data/usn_changes.txt" -ForegroundColor Green

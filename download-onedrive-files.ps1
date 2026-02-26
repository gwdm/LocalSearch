# Download all OneDrive Files-On-Demand files before indexing
# This will materialize all cloud-only placeholder files

Write-Host "Downloading OneDrive Files-On-Demand placeholders..." -ForegroundColor Cyan
Write-Host "This may take a while depending on file count and internet speed..." -ForegroundColor Yellow

# Remove 'Unpinned' attribute (U) recursively on all OneDrive files
# This forces Windows to download cloud-only files
attrib -U /S /D D:\OneDrive\*

Write-Host "`nDone! All OneDrive files are now locally available." -ForegroundColor Green
Write-Host "You can now reprocess the error files." -ForegroundColor Green

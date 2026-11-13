# Windows PowerShell 5+/PowerShell 7. Run in a trusted source checkout.
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Backend dependencies install failed' }
python -m pip install 'pyinstaller>=6.0,<7.0' 'pytest' 'httpx'
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies install failed' }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed, build aborted' }
Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
python -m PyInstaller SteamToolbox.spec --distpath packaged --workpath build --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
$exe = Join-Path $PWD 'packaged/SteamToolbox.exe'
if (-not (Test-Path $exe)) { throw 'Executable not found' }
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  SteamToolbox.exe" | Set-Content -Encoding ascii 'packaged/SHA256SUMS.txt'
Write-Host "Built: $exe"
Write-Host "SHA256: $hash"

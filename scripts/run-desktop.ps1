$ErrorActionPreference = 'Stop'

Write-Host 'Starting Electron desktop (dev mode)...'
Push-Location 'apps\dsa-desktop'
if (!(Test-Path 'node_modules')) {
  npm install
}
npm run dev
Pop-Location

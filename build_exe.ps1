<#
Builds the Windows version of BoardReady, the counterpart of build_dmg.sh:

  dist\BoardReady\                 the app folder (run BoardReady.exe)
  dist\BoardReady-Windows.zip      the same, zipped (unzip anywhere, double-click BoardReady.exe)
  dist\BoardReady-Setup.exe        a per-user installer, when Inno Setup (iscc) is installed

Run it on a Windows 10/11 PC (PyInstaller does not cross-compile), in PowerShell:

  powershell -ExecutionPolicy Bypass -File build_exe.ps1

Needs: Python 3.10-3.13 on PATH (python.org installer, "Add python.exe to PATH") and Node.js
(for the Marp HTML and PDF export, which is bundled into the app). Optional: Inno Setup 6
(winget install JRSoftware.InnoSetup) for the installer. The GitHub Actions workflow
.github/workflows/windows-build.yml does all of this on a hosted Windows runner.

Not inside the app: any API key (each user adds theirs in Settings). The personas are copied from resources\
at build time: after editing a persona file, run sync_resources.sh, then build again. The exe is not code-signed, so Windows
SmartScreen says "Windows protected your PC" once: More info > Run anyway.
#>
$ErrorActionPreference = "Stop"
$Here     = $PSScriptRoot
$MarpVersion = "4.5.1"
$Name  = "BoardReady"
$Build = Join-Path ([IO.Path]::GetTempPath()) "boardready-build"
$Dist  = Join-Path $Here "dist"
Set-Location $Here

function Step($msg) { Write-Host ""; Write-Host $msg -ForegroundColor Cyan }
function Run($exe) {  # run a native command, stop on a non-zero exit code
    & $exe @args
    if ($LASTEXITCODE -ne 0) { throw "$exe failed with exit code $LASTEXITCODE" }
}

if (Test-Path $Build) { Remove-Item $Build -Recurse -Force }
New-Item -ItemType Directory -Force "$Build\data\personas", "$Build\data\styles", $Dist | Out-Null

Step "1/6  Resources"
Copy-Item "$Here\resources\personas\*" "$Build\data\personas"
Copy-Item "$Here\resources\styles\page_afp.css" "$Build\data\styles"
Copy-Item "$Here\web"  "$Build\data\web"  -Recurse
Copy-Item "$Here\site" "$Build\data\site" -Recurse
Get-ChildItem "$Build\data" -Recurse -Force -Filter ".DS_Store" | Remove-Item -Force

Step "2/6  Python environment"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python was not found on PATH." }
Run python -m venv "$Build\venv"
$Py = "$Build\venv\Scripts\python.exe"
Run $Py -m pip install --quiet --upgrade pip
Run $Py -m pip install --quiet pyinstaller pillow anthropic openai openpyxl python-docx "pywebview>=5"

Step "3/6  Icon"
Run $Py -c "from PIL import Image; Image.open(r'$Here\web\icon.png').convert('RGBA').save(r'$Build\AppIcon.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Step "4/6  App (PyInstaller, a few minutes)"
Run $Py -m PyInstaller app.py --noconfirm --windowed --name $Name `
    --icon "$Build\AppIcon.ico" `
    --add-data "$Build\data\web;web" --add-data "$Build\data\site;site" `
    --add-data "$Build\data\personas;personas" --add-data "$Build\data\styles;styles" `
    --hidden-import review_engine `
    --distpath "$Build\dist" --workpath "$Build\work" --specpath "$Build" `
    --log-level WARN
$App = "$Build\dist\$Name"
# PyInstaller 6 keeps its files in _internal; older versions put them next to the exe.
$Res = if (Test-Path "$App\_internal") { "$App\_internal" } else { $App }

Step "5/6  Marp export (Node + Marp CLI $MarpVersion)"
$Node = Get-Command node -ErrorAction SilentlyContinue
if ($Node -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    New-Item -ItemType Directory -Force "$Res\marp" | Out-Null
    Run npm install --prefix "$Res\marp" --no-audit --no-fund --loglevel=error "@marp-team/marp-cli@$MarpVersion"
    Copy-Item $Node.Source "$Res\marp\node.exe"
    Write-Host "     Bundled Node $(& node --version) and Marp CLI $MarpVersion."
} else {
    Write-Host "     Node.js not found: the app will write Markdown, and use npx if the user has Node."
}

Step "6/6  Smoke test"
$port = 8793
$proc = Start-Process "$App\$Name.exe" -ArgumentList "--serve", "--port=$port" -PassThru -WindowStyle Hidden
try {
    $cfg = $null
    for ($i = 0; $i -lt 40 -and -not $cfg; $i++) {
        Start-Sleep -Milliseconds 500
        try { $cfg = Invoke-RestMethod "http://127.0.0.1:$port/api/config" } catch {}
    }
    if (-not $cfg) { throw "The packaged app did not answer on port $port." }
    Write-Host "     OK: $($cfg.personas.Count) personas, Marp bundled: $($cfg.marp.bundled)"
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process $proc -Force }
}

# Ship it
@"
BoardReady
Put your draft in front of the panel before it goes in front of the board.

START
Double-click BoardReady.exe. Windows may say "Windows protected your PC" because the
app is not code-signed: click More info, then Run anyway. Only needed once.
Click Settings, choose your provider and model, and paste your API key.
The key stays on your PC, in %APPDATA%\BoardReady.

USE
Drop a Markdown, Word (.docx), Excel (.xlsx) or CSV file. Tick the personas
(Elena Varga the Skeptical CFO, the Group Controller, the Red-Team Reviewer)
and what you expect from them (criticize, review for consistency, suggest
enrichments). Reviews are saved in Documents\BoardReady as Markdown, HTML and PDF.

The PDF export uses Microsoft Edge or Google Chrome (Edge comes with Windows).
Needs Windows 10 or 11 with the Microsoft Edge WebView2 Runtime (already on Windows 11
and on up-to-date Windows 10).

The personas are fictional. Read every review as a pre-mortem, not a verdict.
Data Wise Academy, AFP 2026 workshop.
"@ | Set-Content "$App\Read Me First.txt" -Encoding UTF8

Remove-Item "$Dist\$Name" -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $App "$Dist\$Name" -Recurse
Remove-Item "$Dist\$Name-Windows.zip" -ErrorAction SilentlyContinue
Compress-Archive -Path "$Dist\$Name" -DestinationPath "$Dist\$Name-Windows.zip"

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) { $iscc = Get-Item "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 }
if ($iscc) {
    $isccPath = if ($iscc.Source) { $iscc.Source } else { $iscc.FullName }
    Step "Installer (Inno Setup)"
    Run $isccPath /Qp "/DSourceDir=$Dist\$Name" "/DIconFile=$Build\AppIcon.ico" "/DOutputDir=$Dist" "$Here\installer.iss"
} else {
    Write-Host "Inno Setup not found: skipped BoardReady-Setup.exe (the zip is enough to run the app)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Built:" -ForegroundColor Green
Get-ChildItem $Dist -Filter "$Name*" | ForEach-Object { "  dist\" + $_.Name }

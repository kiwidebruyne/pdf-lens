param(
  [string]$Source = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
  [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }),
  [ValidateSet("install", "update", "state", "uninstall")][string]$Action = "install"
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$toolDir = Join-Path $CodexHome "tool-envs\pdf-lens"
$uvDir = Join-Path $toolDir "uv"
$uv = Join-Path $uvDir "uv.exe"
$env:UV_INSTALL_DIR = $uvDir
$env:UV_NO_MODIFY_PATH = "1"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $toolDir "python"
$env:UV_CACHE_DIR = Join-Path $toolDir "cache"
New-Item -ItemType Directory -Force -Path $toolDir | Out-Null

if (-not (Test-Path $uv)) {
  Write-Host "Installing private uv under $uvDir"
  $installer = Join-Path ([IO.Path]::GetTempPath()) "uv-install-$PID.ps1"
  try {
    Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile $installer
    & $installer
    if (-not (Test-Path $uv)) { throw "Private uv installation failed." }
  } finally { Remove-Item $installer -Force -ErrorAction SilentlyContinue }
}

function ConvertTo-WindowsArgument {
  param([string]$Value)
  if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
  $builder = New-Object System.Text.StringBuilder
  $slash = [string][char]92
  $quote = [string][char]34
  [void]$builder.Append($quote)
  $slashes = 0
  foreach ($character in $Value.ToCharArray()) {
    if ($character -eq $slash) { $slashes++; continue }
    if ($character -eq $quote) {
      for ($i = 0; $i -lt (2 * $slashes + 1); $i++) { [void]$builder.Append($slash) }
      [void]$builder.Append($quote)
      $slashes = 0
      continue
    }
    for ($i = 0; $i -lt $slashes; $i++) { [void]$builder.Append($slash) }
    $slashes = 0
    [void]$builder.Append($character)
  }
  for ($i = 0; $i -lt (2 * $slashes); $i++) { [void]$builder.Append($slash) }
  [void]$builder.Append($quote)
  return $builder.ToString()
}

function Invoke-NativeCapture {
  param([string]$FilePath, [string[]]$Arguments)
  $temp = [IO.Path]::GetTempPath()
  $stdoutFile = Join-Path $temp "pdf-lens-out-$PID-$([guid]::NewGuid().ToString('N')).txt"
  $stderrFile = Join-Path $temp "pdf-lens-err-$PID-$([guid]::NewGuid().ToString('N')).txt"
  try {
    $argumentLine = (($Arguments | ForEach-Object { ConvertTo-WindowsArgument $_ }) -join " ")
    $process = Start-Process -FilePath $FilePath -ArgumentList $argumentLine -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
    $stdout = if (Test-Path $stdoutFile) { [IO.File]::ReadAllText($stdoutFile) } else { "" }
    $stderr = if (Test-Path $stderrFile) { [IO.File]::ReadAllText($stderrFile) } else { "" }
    [PSCustomObject]@{ ExitCode = $process.ExitCode; StdOut = $stdout; Stderr = $stderr }
  } finally {
    Remove-Item $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
  }
}

function Invoke-PdfLensInstall {
  param([string]$Interpreter, [string]$SelectedAction)
  if ($SelectedAction -eq "install") {
    $helper = Join-Path $Source "scripts\manage_install.py"
    $arguments = @($helper, "--codex-home", $CodexHome, "install", "--source", $Source)
  } else {
    $helper = Join-Path $CodexHome "skills\pdf-lens\scripts\manage_install.py"
    $arguments = @($helper, "--codex-home", $CodexHome, $SelectedAction)
  }
  try {
    $result = Invoke-NativeCapture $Interpreter $arguments
    $script:PdfLensLastOutput = $result.StdOut + $result.Stderr
    $script:PdfLensLastExitCode = $result.ExitCode
    if ($script:PdfLensLastExitCode -in @(3221225781, -1073741515)) { $script:PdfLensLastOutput += "`nA required runtime DLL could not be loaded (Windows status 0xC0000135)." }
  } catch {
    $script:PdfLensLastOutput = $_.Exception.Message
    $script:PdfLensLastExitCode = 1
  }
  if ($script:PdfLensLastOutput) { Write-Host $script:PdfLensLastOutput.TrimEnd() }
  return $script:PdfLensLastExitCode
}

$pythonInstall = Invoke-NativeCapture $uv @("python", "install", "--no-bin", "--no-registry", "3.13")
if ($pythonInstall.ExitCode -ne 0) { throw "Managed Python 3.13 installation failed (exit $($pythonInstall.ExitCode)). $($pythonInstall.Stderr)" }
$pythonResult = Invoke-NativeCapture $uv @("python", "find", "--managed-python", "3.13")
if ($pythonResult.ExitCode -ne 0) { throw "Could not locate managed Python 3.13. $($pythonResult.Stderr)" }
$python = $pythonResult.StdOut.Trim().Split("`n")[-1].Trim()
if (-not (Test-Path $python)) { throw "Could not locate managed Python 3.13." }

$exitCode = Invoke-PdfLensInstall $python $Action
if ($exitCode -ne 0) {
  # Escalate only when the managed interpreter or a native wheel reports a missing VC runtime DLL.
  if ($script:PdfLensLastOutput -match "(?i)DLL load failed|VCRUNTIME140|MSVCP140|0xC0000135") {
    $machineResult = Invoke-NativeCapture $python @("-c", "import platform; print(platform.machine().lower())")
    $machine = $machineResult.StdOut.Trim()
    $arch = if ($machine -match "arm64|aarch64") { "arm64" } else { "x64" }
    Write-Warning "A Microsoft Visual C++ runtime DLL is missing. Windows will ask for elevation to install Microsoft's official $arch runtime."
    $redist = Join-Path ([IO.Path]::GetTempPath()) "pdf-lens-vc-redist-$PID.exe"
    try {
      Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.$arch.exe" -OutFile $redist
      $signature = Get-AuthenticodeSignature $redist
      if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Microsoft Corporation") {
        throw "The downloaded Visual C++ installer did not pass Microsoft's signature check."
      }
      $process = Start-Process -FilePath $redist -Verb RunAs -Wait -PassThru -ArgumentList @("/install", "/quiet", "/norestart")
      if ($process.ExitCode -notin @(0, 3010)) { throw "Microsoft Visual C++ setup failed (exit $($process.ExitCode))." }
    } finally { Remove-Item $redist -Force -ErrorAction SilentlyContinue }
    $exitCode = Invoke-PdfLensInstall $python $Action
  }
}
if ($exitCode -ne 0) { throw "PDF Lens setup failed (exit $exitCode). See the message above and rerun bootstrap after resolving it." }
if ($Action -eq "uninstall") { Remove-Item $toolDir -Recurse -Force }

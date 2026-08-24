# 按当前平台下载自包含的 Allure CLI + JRE 到 tools/（Windows PowerShell 版）。
# 幂等：已存在则跳过。tools/allure 与 tools/jre 为机器专属二进制，勿入版本库。
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
New-Item -ItemType Directory -Force -Path $Tools | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Tools "bin") | Out-Null

if ((Test-Path (Join-Path $Tools "bin\allure.cmd")) -and (Test-Path (Join-Path $Tools "jre\bin\java.exe"))) {
  Write-Host "Allure 已就绪：$Tools\bin\allure.cmd"
  exit 0
}

# ---- Allure CLI（跨平台单一发行包，内含 allure.bat）----
if (-not (Test-Path (Join-Path $Tools "allure"))) {
  Write-Host "下载 Allure CLI…"
  Invoke-WebRequest -Uri "https://github.com/allure-framework/allure2/releases/download/2.32.2/allure-2.32.2.tgz" -OutFile (Join-Path $Tools "allure.tgz")
  tar -xzf (Join-Path $Tools "allure.tgz") -C $Tools
  Move-Item (Join-Path $Tools "allure-2.32.2") (Join-Path $Tools "allure")
  Remove-Item (Join-Path $Tools "allure.tgz")
}

# ---- JRE（Windows x64）----
if (-not (Test-Path (Join-Path $Tools "jre"))) {
  Write-Host "下载 JRE（windows/x64）…"
  Invoke-WebRequest -Uri "https://api.adoptium.net/v3/binary/latest/11/ga/windows/x64/jre/hotspot/normal/eclipse" -OutFile (Join-Path $Tools "jre.zip")
  Expand-Archive (Join-Path $Tools "jre.zip") -DestinationPath $Tools -Force
  $dir = Get-ChildItem $Tools -Directory | Where-Object { $_.Name -like "jdk-11*-jre" } | Select-Object -First 1
  if ($null -eq $dir) { Write-Error "解压后未找到 JRE 目录"; exit 1 }
  Rename-Item $dir.FullName (Join-Path $Tools "jre")
  Remove-Item (Join-Path $Tools "jre.zip")
}

# ---- 启动器（cmd）----
@"
@echo off
set DIR=%~dp0..
set JAVA_HOME=%DIR%\jre
"%DIR%\allure\bin\allure.bat" %*
"@ | Out-File -Encoding ascii (Join-Path $Tools "bin\allure.cmd")

& (Join-Path $Tools "bin\allure.cmd") --version
Write-Host "Allure 就绪：$Tools\bin\allure.cmd"

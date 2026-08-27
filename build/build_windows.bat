@echo off
setlocal
set ROOT=%~dp0..
set BIN_DIR=%ROOT%\build\bin\windows
set FFMPEG=%BIN_DIR%\ffmpeg.exe
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"
if not exist "%FFMPEG%" (
  echo Downloading ffmpeg (windows)...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%TEMP%\ffmpeg-win.zip'"
  if errorlevel 1 (
    echo ERROR: ffmpeg download failed >&2
    exit /b 1
  )
  powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\ffmpeg-win.zip' -DestinationPath '%TEMP%\ffmpeg-win-x' -Force"
  if errorlevel 1 (
    echo ERROR: ffmpeg extract failed >&2
    exit /b 1
  )
  for /r "%TEMP%\ffmpeg-win-x" %%F in (ffmpeg.exe) do copy /y "%%F" "%FFMPEG%" >nul
)
if not exist "%FFMPEG%" (
  echo ERROR: ffmpeg.exe not found at %FFMPEG% >&2
  exit /b 1
)
cd /d "%ROOT%"
python -m PyInstaller --noconfirm build\app.spec
if errorlevel 1 exit /b 1
echo Build output: %ROOT%\dist\concat-e3v.exe
endlocal
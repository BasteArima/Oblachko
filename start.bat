@echo off
rem Oblachko: updates itself, sets everything up on the first run and starts the server.
rem System tools are called by full path and uv is looked up in its usual install folders:
rem when PATH is longer than cmd's 8191-character limit, cmd stops finding any program by name.
setlocal
set "SYS=%SystemRoot%\System32"
"%SYS%\chcp.com" 65001 >nul
cd /d "%~dp0"

rem The updater can't overwrite a running batch file, it leaves start.bat.new instead.
rem The whole block is parsed before it runs, so replacing the file here is safe.
if exist start.bat.new (
    copy /y start.bat.new start.bat >nul
    del start.bat.new
    "%~f0"
)

set "UV="
for /f "delims=" %%i in ('""%SYS%\where.exe" uv 2>nul"') do if not defined UV set "UV=%%i"
for %%p in ("%USERPROFILE%\.local\bin\uv.exe" "%USERPROFILE%\.cargo\bin\uv.exe" "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe") do (
    if not defined UV if exist %%p set "UV=%%~p"
)
if not defined UV (
    echo Не найден uv. Установите его командой в PowerShell:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo и запустите start.bat ещё раз.
    goto fail
)

echo Проверяю обновления...
"%UV%" run --no-project --python 3.12 python server\update.py
if exist start.bat.new (
    copy /y start.bat.new start.bat >nul
    del start.bat.new
    "%~f0"
)

cd server

if not exist models\comictextdetector.pt.onnx (
    echo Скачиваю детектор текста, около 95 МБ...
    if not exist models mkdir models
    "%SYS%\curl.exe" -L --fail -o models\comictextdetector.pt.onnx https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/comictextdetector.pt.onnx
    if errorlevel 1 goto fail
)

if not exist config.toml (
    copy config.example.toml config.toml >nul
    echo Создан server\config.toml. Если LM Studio слушает не порт 1234, поправьте в нём llm_base_url.
)

echo Проверяю зависимости. В первый раз это займёт несколько минут...
"%UV%" sync
if errorlevel 1 goto fail

echo Запускаю сервер. Первый запуск скачает модель OCR, около 450 МБ.
echo Окно не закрывайте, пока пользуетесь переводом.
"%UV%" run python -m app
goto end

:fail
echo.
echo Что-то пошло не так, смотрите сообщения выше.

:end
pause

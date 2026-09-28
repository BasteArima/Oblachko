@echo off
rem Oblachko: updates itself, sets everything up on the first run and starts the server.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem The updater can't overwrite a running batch file, it leaves start.bat.new instead.
rem The whole block is parsed before it runs, so replacing the file here is safe.
if exist start.bat.new (
    copy /y start.bat.new start.bat >nul
    del start.bat.new
    "%~f0"
)

where uv >nul 2>nul
if errorlevel 1 (
    echo Не найден uv. Установите его командой в PowerShell:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo и запустите start.bat ещё раз.
    goto fail
)

echo Проверяю обновления...
uv run --no-project --python 3.12 python server\update.py
if exist start.bat.new (
    copy /y start.bat.new start.bat >nul
    del start.bat.new
    "%~f0"
)

cd server

if not exist models\comictextdetector.pt.onnx (
    echo Скачиваю детектор текста, около 95 МБ...
    if not exist models mkdir models
    curl -L --fail -o models\comictextdetector.pt.onnx https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/comictextdetector.pt.onnx
    if errorlevel 1 goto fail
)

if not exist config.toml (
    copy config.example.toml config.toml >nul
    echo Создан server\config.toml. Если LM Studio слушает не порт 1234, поправьте в нём llm_base_url.
)

echo Проверяю зависимости. В первый раз это займёт несколько минут...
uv sync
if errorlevel 1 goto fail

echo Запускаю сервер. Первый запуск скачает модель OCR, около 450 МБ.
echo Окно не закрывайте, пока пользуетесь переводом.
uv run python -m app
goto end

:fail
echo.
echo Что-то пошло не так, смотрите сообщения выше.

:end
pause

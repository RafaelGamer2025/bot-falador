@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher nao encontrado. Instale Python 3.10 ou mais novo.
    pause
    exit /b 1
)
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Foi criado .env. Abra esse arquivo e coloque DISCORD_TOKEN.
    notepad ".env"
    echo Depois de salvar o token, execute este BAT novamente.
    pause
    exit /b 1
)
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo Falha ao instalar dependencias. Confira a conexao e tente novamente.
    pause
    exit /b 1
)
py bot.py
if errorlevel 1 echo O bot encerrou com erro. Confira o token e a configuracao dos intents no Developer Portal.
pause

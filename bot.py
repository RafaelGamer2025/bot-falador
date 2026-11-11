from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

import discord
import pyttsx3
import requests
from discord.ext import commands

FACT_API_URL = "https://uselessfacts.jsph.pl/api/v2/facts/random"
WEATHER_API_BASE = "https://wttr.in"
VOICE_CHANNEL_NAME = "áudio-descrição-do-clima"
REQUEST_TIMEOUT = 12
MAX_FACT_CHARS = 1600
MAX_SPEECH_CHARS = 900
SPEECH_RATE = 180

_ENV_FILE = Path(__file__).resolve().with_name(".env")
_SPEECH_LOCK = threading.Lock()


def load_local_env(path: Path = _ENV_FILE) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"Não foi possível ler .env ({type(exc).__name__}).")
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value


def speak(text: str) -> None:
    spoken_text = " ".join(text.split())[:MAX_SPEECH_CHARS]
    if not spoken_text:
        return
    with _SPEECH_LOCK:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", SPEECH_RATE)
            print(f"🔊 Falando localmente: {spoken_text}")
            engine.say(spoken_text)
            engine.runAndWait()
        except Exception as exc:  # noqa: BLE001
            print(f"Não foi possível reproduzir a fala local ({type(exc).__name__}).")


def extract_fact(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    text = payload.get("text")
    if not isinstance(text, str):
        return None
    clean = " ".join(text.split())
    return clean or None


def format_weather(city: str, payload: Any) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return None
    conditions = payload.get("current_condition")
    if not isinstance(conditions, list) or not conditions or not isinstance(conditions[0], dict):
        return None
    current = conditions[0]

    def value(key: str, fallback: str = "?") -> str:
        raw = current.get(key)
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            raw = raw[0].get("value")
        if raw is None:
            return fallback
        return str(raw).strip() or fallback

    temperature = value("temp_C")
    feels_like = value("FeelsLikeC")
    description = value("weatherDesc", "Condição não informada")
    humidity = value("humidity")
    wind = value("windspeedKmph")
    city_name = city.strip().title()
    message = (
        f"**Previsão atual para {city_name}**\n"
        f"• Condição: {description}\n"
        f"• Temperatura: {temperature} °C (sensação: {feels_like} °C)\n"
        f"• Umidade: {humidity}%\n"
        f"• Vento: {wind} km/h"
    )
    speech = f"A temperatura em {city_name} é de {temperature} graus Celsius, com {description}."
    return message, speech


intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    allowed_mentions=discord.AllowedMentions.none(),
    help_command=None,
)


@bot.event
async def on_ready() -> None:
    print(f"Bot conectado como {bot.user}.")
    print("Comandos: !start, !fact, !weather <cidade>.")


@bot.command(name="start")
async def start(ctx: commands.Context) -> None:
    message = (
        "Olá! Bem-vindo ao bot de fatos e clima.\n"
        "Use `!fact` para receber uma curiosidade (e ouvi-la no computador do bot) "
        "ou `!weather <cidade>` para consultar a previsão."
    )
    await ctx.send(message)


@bot.command(name="fact")
@commands.cooldown(1, 4, commands.BucketType.user)
async def fact(ctx: commands.Context) -> None:
    await ctx.typing()
    try:
        # Alterado para a v2 da API especificando o idioma português (pt)
        response = await asyncio.to_thread(
            requests.get,
            FACT_API_URL,
            params={"language": "pt"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"Falha de rede na API de fatos ({type(exc).__name__}).")
        await ctx.send("Não consegui acessar a API de fatos agora. Tente novamente daqui a pouco.")
        return

    if response.status_code != 200:
        await ctx.send(
            f"A API de fatos respondeu com status HTTP {response.status_code}. Tente novamente mais tarde."
        )
        return

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        await ctx.send("A API respondeu, mas os dados não estavam em JSON válido.")
        return

    print("Resposta da API de fatos:", data)
    fact_text = extract_fact(data)
    if not fact_text:
        await ctx.send("A resposta da API não continha o campo `text` com o fato.")
        return

    text_message = f"Curiosidade: {fact_text}"
    if len(text_message) > MAX_FACT_CHARS:
        text_message = text_message[: MAX_FACT_CHARS - 1].rstrip() + "…"
    await ctx.send(text_message)
    await asyncio.to_thread(speak, fact_text)


@bot.command(name="weather")
@commands.cooldown(1, 8, commands.BucketType.user)
async def weather(ctx: commands.Context, *, cidade: str) -> None:
    city = " ".join(cidade.split())
    if not city or len(city) > 100:
        await ctx.send("Informe uma cidade com até 100 caracteres. Exemplo: `!weather São Paulo`.")
        return

    city_path = quote(city, safe="")
    url = f"{WEATHER_API_BASE}/{city_path}"
    try:
        response = await asyncio.to_thread(
            requests.get,
            url,
            params={"format": "j1"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"Falha de rede na API do clima ({type(exc).__name__}).")
        await ctx.send("Não consegui acessar a previsão do tempo agora. Tente novamente daqui a pouco.")
        return

    if response.status_code != 200:
        await ctx.send(f"A consulta do clima falhou (HTTP {response.status_code}). Confira a cidade e tente de novo.")
        return
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        await ctx.send("O serviço de clima não retornou JSON válido.")
        return

    formatted = format_weather(city, data)
    if not formatted:
        await ctx.send("Não encontrei uma previsão utilizável para essa cidade.")
        return
    message, speech = formatted
    await ctx.send(message)
    await asyncio.to_thread(speak, speech)

    guild = ctx.guild
    if guild is None:
        return

    category = getattr(ctx.channel, "category", None)
    voice_channel = next(
        (
            channel
            for channel in guild.voice_channels
            if channel.name == VOICE_CHANNEL_NAME and channel.category == category
        ),
        None,
    )
    try:
        if voice_channel is None:
            voice_channel = await guild.create_voice_channel(
                name=VOICE_CHANNEL_NAME,
                category=category,
                reason=f"Canal de áudio descrição solicitado por {ctx.author}",
            )
    except discord.Forbidden:
        await ctx.send(
            "A previsão foi enviada e lida localmente, mas não tenho permissão para criar o canal. "
            "Peça ao administrador a permissão Gerenciar Canais."
        )
        return
    except discord.HTTPException as exc:
        print(f"Falha ao criar canal de voz ({type(exc).__name__}).")
        await ctx.send("A previsão foi enviada, mas houve um erro do Discord ao criar o canal de voz.")
        return

    voice_state = getattr(ctx.author, "voice", None)
    if voice_state is None or getattr(voice_state, "channel", None) is None:
        await ctx.send(
            f"Canal de voz criado/reutilizado: **{VOICE_CHANNEL_NAME}**. "
            "Você não estava em uma chamada, então não movi sua conta."
        )
        return

    try:
        await ctx.author.move_to(voice_channel, reason="Áudio descrição do clima solicitada pelo próprio usuário")
        await ctx.send(f"Você foi movido para **{VOICE_CHANNEL_NAME}**.")
    except discord.Forbidden:
        await ctx.send(
            f"Canal **{VOICE_CHANNEL_NAME}** pronto, mas não consegui mover você. "
            "O bot precisa da permissão Mover Membros."
        )
    except discord.HTTPException as exc:
        print(f"Falha ao mover membro ({type(exc).__name__}).")
        await ctx.send("O canal foi preparado, mas o Discord não conseguiu mover você.")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Espere {error.retry_after:.1f} s antes de usar esse comando novamente.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Use `!weather <cidade>`. Exemplo: `!weather Lisboa`.")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        print(f"Erro em comando ({type(error).__name__}).")
        await ctx.send("Ocorreu um erro ao executar o comando. Tente novamente ou avise o tutor.")


def main() -> None:
    load_local_env()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "COLOQUE_O_TOKEN_AQUI":
        raise SystemExit(
            "Token não configurado. Copie .env.example para .env e preencha DISCORD_TOKEN no seu computador."
        )
    bot.run(token)


if __name__ == "__main__":
    main()
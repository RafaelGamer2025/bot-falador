from __future__ import annotations

import asyncio
import json
import os
import random
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote

import discord
import pyttsx3
import requests
from discord.ext import commands

WIKIPEDIA_API_URL = "https://pt.wikipedia.org/w/api.php"
WIKIPEDIA_ARTICLE_BASE = "https://pt.wikipedia.org/wiki/"
WEATHER_API_BASE = "https://wttr.in"
VOICE_CHANNEL_NAME = "audio-descricao-do-clima"
REQUEST_TIMEOUT = 15
MAX_FACT_CHARS = 1700
MAX_SPEECH_CHARS = 900
SPEECH_RATE = 180
CATEGORY_CACHE_SECONDS = 6 * 60 * 60
GLOBAL_FACT_DELAY_SECONDS = 2.0

TOPICS = {
    "ciencia": {"name": "Ciência", "category": "Categoria:Ciência"},
    "historia": {"name": "História", "category": "Categoria:História"},
    "astronomia": {"name": "Astronomia", "category": "Categoria:Astronomia"},
}
RANDOM_TOPIC = "aleatorio"
VOICE_CHOICES = {"masculina", "feminina", "sistema"}
PHILOSOPHY_CARDS = (
    {
        "key": "tempo",
        "title": "A fita do tempo e o universo 4D",
        "text": (
            "Imagine uma esfera 3D atravessando um mundo 2D: os habitantes veriam cortes — "
            "um ponto que vira um círculo maior e depois diminui. Por analogia, podemos imaginar "
            "a história de algo como uma estrutura no espaço-tempo 4D. Mas essa imagem não prova "
            "que o futuro já exista. O presentismo diz que só o presente existe; o eternalismo "
            "considera passado e futuro partes da realidade. São interpretações filosóficas debatidas."
        ),
        "question": "O futuro já está na fita ou ainda está sendo escrito? E você continua sendo a pessoa do passado?",
        "source": "https://plato.stanford.edu/entries/time/",
    },
    {
        "key": "identidade",
        "title": "Você ainda é a mesma pessoa?",
        "text": (
            "Seu corpo, suas opiniões e seus hábitos mudam. Algumas teorias destacam a continuidade "
            "do organismo; outras, conexões psicológicas como memórias, intenções e personalidade. "
            "Não há um teste simples que encerre o debate: filósofos discordam sobre qual continuidade "
            "é decisiva. Mudar muito não demonstra, por si só, que uma pessoa antiga desapareceu."
        ),
        "question": "O que precisa permanecer para você dizer que ainda é você: corpo, memória, caráter ou a história que conta sobre si?",
        "source": "https://plato.stanford.edu/entries/identity-personal/",
    },
    {
        "key": "teseu",
        "title": "O navio de Teseu",
        "text": (
            "Imagine um navio cujas peças são trocadas uma a uma. No fim, nenhuma peça original "
            "resta. Ele ainda é o mesmo navio? E se alguém remontar outro barco com todas as peças "
            "antigas, qual dos dois merece o nome original? O experimento separa matéria, forma, "
            "continuidade e história — critérios que podem apontar para respostas diferentes."
        ),
        "question": "Se suas células, lembranças e ideias mudam, o que faz sua vida parecer uma única história?",
        "source": "https://plato.stanford.edu/entries/identity-personal/",
    },
    {
        "key": "memoria",
        "title": "Você é as suas lembranças?",
        "text": (
            "Memórias conectam o presente ao passado, mas não são uma gravação perfeita: lembramos "
            "algumas coisas, esquecemos outras e reinterpretamos experiências. Uma visão da identidade "
            "dá grande peso à continuidade psicológica; outras também valorizam o corpo e a continuidade "
            "da vida. A questão não tem uma resposta única aceita por todos os filósofos."
        ),
        "question": "Se você perdesse uma lembrança importante, seria menos você — ou continuaria sendo você de outro jeito?",
        "source": "https://plato.stanford.edu/entries/identity-personal/",
    },
    {
        "key": "livre-arbitrio",
        "title": "Nossas escolhas são livres?",
        "text": (
            "Muitas decisões têm causas: educação, ambiente, desejos e experiências. Uma pergunta "
            "filosófica é se ter causas elimina a liberdade. Algumas posições dizem que sim; outras "
            "defendem que podemos ser livres quando agimos segundo nossas razões, sem coerção, mesmo "
            "num mundo causal. O debate depende também do que chamamos de liberdade."
        ),
        "question": "Uma escolha ainda é sua se ela foi influenciada por tudo o que aconteceu antes?",
        "source": "https://plato.stanford.edu/entries/freewill/",
    },
    {
        "key": "teletransporte",
        "title": "O teletransportador e a cópia perfeita",
        "text": (
            "Imagine uma máquina que registra cada detalhe seu, destrói seu corpo e cria uma cópia "
            "idêntica em outro lugar, com as mesmas lembranças. A pessoa que acorda é você ou uma "
            "cópia convencida de que é você? O exemplo testa se identidade depende do corpo original, "
            "da continuidade psicológica ou de outra coisa. É um experimento mental, não uma tecnologia real."
        ),
        "question": "Você entraria na máquina? O que teria que continuar para você aceitar que sobreviveu?",
        "source": "https://plato.stanford.edu/entries/identity-personal/",
    },
)
PHILOSOPHY_ALIASES = {
    "tempo": "tempo",
    "universo4d": "tempo",
    "fita": "tempo",
    "identidade": "identidade",
    "eu": "identidade",
    "teseu": "teseu",
    "navio": "teseu",
    "memoria": "memoria",
    "livrearbitrio": "livre-arbitrio",
    "liberdade": "livre-arbitrio",
    "teletransporte": "teletransporte",
    "copia": "teletransporte",
}

_ENV_FILE = Path(__file__).resolve().with_name(".env")
_PREFERENCES_FILE = Path(__file__).resolve().with_name("preferencias.json")
_SPEECH_LOCK = threading.Lock()
_CATEGORY_CACHE_LOCK = threading.Lock()
_CATEGORY_CACHE: dict[str, tuple[float, list[str]]] = {}
_FACT_API_LOCK = asyncio.Lock()
_LAST_FACT_API_CALL = 0.0


class WikimediaAPIError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


class PreferenceStore:
    """Guarda preferências locais em JSON e nunca armazena o token do Discord."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "users": {}}
        if not isinstance(value, dict) or not isinstance(value.get("users"), dict):
            return {"version": 1, "users": {}}
        return value

    def get(self, user_id: int | str, key: str, default: str) -> str:
        if key not in {"voz", "tema"}:
            return default
        with self.lock:
            record = self._read()["users"].get(str(user_id), {})
            if not isinstance(record, dict):
                return default
            value = record.get(key, default)
            return value if isinstance(value, str) else default

    def set(self, user_id: int | str, key: str, value: str) -> None:
        if key == "voz" and value not in VOICE_CHOICES:
            raise ValueError("Preferência de voz inválida.")
        if key == "tema" and value not in (*TOPICS.keys(), RANDOM_TOPIC):
            raise ValueError("Preferência de tema inválida.")
        if key not in {"voz", "tema"}:
            raise ValueError("Tipo de preferência inválido.")
        with self.lock:
            data = self._read()
            users = data.setdefault("users", {})
            record = users.setdefault(str(user_id), {})
            if not isinstance(record, dict):
                record = {}
                users[str(user_id)] = record
            record[key] = value
            data["version"] = 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)


PREFERENCES = PreferenceStore(_PREFERENCES_FILE)


def load_local_env(path: Path = _ENV_FILE) -> None:
    """Carrega linhas simples KEY=value sem exibir nem enviar informações secretas."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"Não foi possível ler o arquivo .env ({type(exc).__name__}).")
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


def _plain_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def normalize_topic(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _plain_text(value.strip()).replace(" ", "")
    aliases = {
        "ciencia": "ciencia",
        "science": "ciencia",
        "historia": "historia",
        "history": "historia",
        "astronomia": "astronomia",
        "astronomy": "astronomia",
        "aleatorio": RANDOM_TOPIC,
        "aleatoria": RANDOM_TOPIC,
        "sorteado": RANDOM_TOPIC,
        "random": RANDOM_TOPIC,
        "todos": RANDOM_TOPIC,
    }
    return aliases.get(cleaned)


def normalize_voice_choice(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _plain_text(value.strip()).replace(" ", "")
    aliases = {
        "masculina": "masculina",
        "masculino": "masculina",
        "male": "masculina",
        "feminina": "feminina",
        "feminino": "feminina",
        "female": "feminina",
        "sistema": "sistema",
        "padrao": "sistema",
        "default": "sistema",
        "listar": "listar",
        "list": "listar",
    }
    return aliases.get(cleaned)


def choose_philosophy_reflection(topic: str | None = None) -> dict[str, str] | None:
    """Escolhe uma reflexão somente quando o comando de filosofia é chamado."""
    if topic is None or not topic.strip():
        return random.choice(PHILOSOPHY_CARDS)
    normalized = _plain_text(topic.strip()).replace(" ", "").replace("-", "")
    key = PHILOSOPHY_ALIASES.get(normalized)
    return next((card for card in PHILOSOPHY_CARDS if card["key"] == key), None)


def format_philosophy_message(card: dict[str, str]) -> str:
    return (
        f"**Reflexão filosófica — {card['title']}**\n{card['text']}\n\n"
        f"**Pra pensar:** {card['question']}\n"
        f"Leitura de referência: [Stanford Encyclopedia of Philosophy]({card['source']})."
    )


def _wikimedia_headers() -> dict[str, str]:
    contact = os.getenv("WIKIMEDIA_CONTACT", "").strip()
    user_agent = "DiscordFatosTTS/1.1 (bot educacional em português)"
    if contact:
        user_agent += f"; contato: {contact}"
    return {"User-Agent": user_agent, "Accept": "application/json"}


def _get_json(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, headers=_wikimedia_headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise WikimediaAPIError(response.status_code)
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise WikimediaAPIError(response.status_code, "A API não retornou JSON válido.") from exc
    if not isinstance(data, dict):
        raise WikimediaAPIError(response.status_code, "Formato inesperado da API.")
    if "error" in data:
        info = data["error"].get("info", "") if isinstance(data["error"], dict) else ""
        raise WikimediaAPIError(response.status_code, str(info))
    return data


def _category_titles(topic: str) -> list[str]:
    details = TOPICS[topic]
    category = details["category"]
    now = time.monotonic()
    with _CATEGORY_CACHE_LOCK:
        cached = _CATEGORY_CACHE.get(category)
        if cached and now - cached[0] < CATEGORY_CACHE_SECONDS:
            return cached[1].copy()

    data = _get_json(
        WIKIPEDIA_API_URL,
        params={
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": "page",
            "cmnamespace": 0,
            "cmlimit": 100,
            "format": "json",
            "formatversion": 2,
            "maxlag": 5,
        },
    )
    query = data.get("query", {})
    members = query.get("categorymembers", []) if isinstance(query, dict) else []
    if not isinstance(members, list):
        raise WikimediaAPIError(200, "A API não retornou uma lista de artigos.")
    titles = [
        member["title"]
        for member in members
        if isinstance(member, dict)
        and isinstance(member.get("title"), str)
        and member.get("ns") == 0
    ]
    if not titles:
        raise WikimediaAPIError(200, f"Não encontrei artigos na categoria {details['name']}.")
    with _CATEGORY_CACHE_LOCK:
        _CATEGORY_CACHE[category] = (time.monotonic(), titles.copy())
    return titles


def _article_fact(title: str, topic: str) -> dict[str, str] | None:
    data = _get_json(
        WIKIPEDIA_API_URL,
        params={
            "action": "query",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "exsentences": 4,
            "redirects": 1,
            "titles": title,
            "format": "json",
            "formatversion": 2,
            "maxlag": 5,
        },
    )
    query = data.get("query", {})
    pages = query.get("pages", []) if isinstance(query, dict) else []
    if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
        return None
    page = pages[0]
    if page.get("missing") is not None:
        return None
    extract = page.get("extract")
    page_title = page.get("title")
    if not isinstance(extract, str) or not isinstance(page_title, str):
        return None
    extract = re.sub(r"\s+", " ", extract).strip()
    if len(extract) < 80:
        return None
    if "pode referir-se a" in _plain_text(extract[:400]):
        return None
    if len(extract) > 1100:
        cutoff = extract.rfind(". ", 0, 1100)
        extract = extract[:cutoff + 1] if cutoff >= 350 else extract[:1099].rstrip() + "…"
    article_slug = quote(page_title.replace(" ", "_"), safe="_")
    article_url = WIKIPEDIA_ARTICLE_BASE + article_slug
    return {
        "tema": TOPICS[topic]["name"],
        "titulo": page_title,
        "texto": extract,
        "url": article_url,
    }


def fetch_thematic_fact(topic: str) -> dict[str, str]:
    """Busca uma introdução curta em uma categoria temática da Wikipédia em português."""
    if topic not in TOPICS:
        raise ValueError("Tema inválido.")
    titles = _category_titles(topic)
    candidates = random.sample(titles, k=min(12, len(titles)))
    for title in candidates:
        fact = _article_fact(title, topic)
        if fact:
            return fact
    raise WikimediaAPIError(200, f"Não encontrei um resumo utilizável para {TOPICS[topic]['name']}.")


def format_fact_message(fact: dict[str, str]) -> str:
    theme = fact["tema"]
    title = fact["titulo"]
    text = fact["texto"]
    url = fact["url"]
    body = f"**{title}**\n{text}"
    message = (
        f"**Curiosidade de {theme}**\n{body}\n\n"
        f"Fonte: [Wikipédia em português]({url}) · resumo adaptado, licença [CC BY-SA 4.0]"
        "(https://creativecommons.org/licenses/by-sa/4.0/)."
    )
    if len(message) > MAX_FACT_CHARS:
        room = MAX_FACT_CHARS - len(message) + len(text) - 1
        shortened = text[:max(room, 0)].rsplit(" ", 1)[0].rstrip(" .,;:") + "…"
        message = (
            f"**Curiosidade de {theme}**\n**{title}**\n{shortened}\n\n"
            f"Fonte: [Wikipédia em português]({url}) · resumo adaptado, licença [CC BY-SA 4.0]"
            "(https://creativecommons.org/licenses/by-sa/4.0/)."
        )
    return message


def _voice_gender(voice: Any) -> str | None:
    gender = str(getattr(voice, "gender", "") or "").casefold()
    identity = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".casefold()
    if any(word in gender for word in ("female", "femin", "woman")):
        return "feminina"
    if any(word in gender for word in ("male", "mascul", "man")):
        return "masculina"
    female_names = (
        "zira", "hazel", "susan", "heather", "helena", "maria", "victoria",
        "aria", "jenny", "samantha", "joana", "luciana", "raquel", "fernanda",
        "francisca", "female", "woman", "feminina",
    )
    male_names = (
        "david", "mark", "george", "james", "paul", "ryan", "guy", "daniel",
        "carlos", "bruno", "miguel", "masculino", "male", "man",
    )
    if any(name in identity for name in female_names):
        return "feminina"
    if any(name in identity for name in male_names):
        return "masculina"
    return None


def _voice_languages(voice: Any) -> str:
    languages = getattr(voice, "languages", ()) or ()
    parts: list[str] = []
    for language in languages:
        if isinstance(language, bytes):
            language = language.decode("utf-8", errors="ignore")
        parts.append(str(language).casefold())
    return " ".join(parts)


def _voice_is_portuguese(voice: Any) -> bool:
    info = _voice_languages(voice) + " " + str(getattr(voice, "name", "")).casefold()
    return any(marker in info for marker in ("pt-br", "pt_br", "pt-brasil", "portuguese", "português", "brazil", "brasil"))


def choose_system_voice(voices: list[Any], gender: str) -> Any | None:
    matches = [voice for voice in voices if _voice_gender(voice) == gender]
    if not matches:
        return None
    return max(matches, key=lambda voice: (_voice_is_portuguese(voice), str(getattr(voice, "name", ""))))


def list_system_voices() -> list[dict[str, str]]:
    """Lista vozes locais instaladas; a detecção de gênero e idioma é aproximada."""
    with _SPEECH_LOCK:
        engine = None
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []
            result = []
            for voice in voices:
                result.append(
                    {
                        "id": str(getattr(voice, "id", "")),
                        "name": str(getattr(voice, "name", "Voz sem nome")),
                        "gender": _voice_gender(voice) or "não identificada",
                        "portuguese": "sim" if _voice_is_portuguese(voice) else "não identificado",
                    }
                )
            return result
        finally:
            if engine is not None:
                try:
                    engine.stop()
                except Exception as exc:  # noqa: BLE001  # O encerramento varia conforme o mecanismo de voz do sistema.
                    print(f"Limpeza do mecanismo de voz não disponível ({type(exc).__name__}).")


def local_voice_available(gender: str) -> bool:
    with _SPEECH_LOCK:
        engine = None
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []
            return choose_system_voice(voices, gender) is not None
        finally:
            if engine is not None:
                try:
                    engine.stop()
                except Exception as exc:  # noqa: BLE001  # O encerramento varia conforme o mecanismo de voz do sistema.
                    print(f"Limpeza do mecanismo de voz não disponível ({type(exc).__name__}).")


def speak(text: str, voice_choice: str = "sistema") -> None:
    """Lê o texto pelo pyttsx3 no computador do bot, sem transmitir para o canal de voz."""
    spoken_text = " ".join(text.split())[:MAX_SPEECH_CHARS]
    if not spoken_text:
        return
    with _SPEECH_LOCK:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", SPEECH_RATE)
            if voice_choice in {"masculina", "feminina"}:
                voices = engine.getProperty("voices") or []
                selected_voice = choose_system_voice(voices, voice_choice)
                if selected_voice is not None:
                    engine.setProperty("voice", selected_voice.id)
                else:
                    print(f"Não encontrei voz {voice_choice} instalada; usando a voz padrão do sistema.")
            print(f"🔊 Fala local ({voice_choice}): {spoken_text}")
            engine.say(spoken_text)
            engine.runAndWait()
        except Exception as exc:  # noqa: BLE001  # Os erros variam entre os mecanismos de voz de cada sistema.
            print(f"Não foi possível reproduzir a fala local ({type(exc).__name__}).")


def translate_weather_condition(description: str) -> str:
    """Traduz descrições comuns do wttr.in e preserva termos desconhecidos do serviço."""
    clean = " ".join(description.split())
    normalized = _plain_text(clean)
    exact = {
        "patchy rain nearby": "Chuva irregular nas proximidades",
        "patchy light rain nearby": "Chuva fraca e irregular nas proximidades",
        "light rain": "Chuva fraca",
        "moderate rain": "Chuva moderada",
        "heavy rain": "Chuva forte",
        "light drizzle": "Garoa fraca",
        "moderate or heavy rain shower": "Pancadas de chuva moderadas ou fortes",
        "thundery outbreaks possible": "Possibilidade de trovoadas",
        "partly cloudy": "Parcialmente nublado",
        "mostly cloudy": "Predominantemente nublado",
        "cloudy": "Nublado",
        "overcast": "Encoberto",
        "sunny": "Ensolarado",
        "clear": "Céu limpo",
        "mist": "Névoa",
        "fog": "Neblina",
        "light snow": "Neve fraca",
        "moderate snow": "Neve moderada",
        "heavy snow": "Neve intensa",
        "patchy snow nearby": "Neve irregular nas proximidades",
    }
    if normalized in exact:
        return exact[normalized]
    if "thunder" in normalized:
        return "Trovoadas"
    if "snow" in normalized or "sleet" in normalized:
        return "Neve ou chuva congelada"
    if "rain" in normalized or "drizzle" in normalized:
        return "Chuva ou garoa"
    if "cloud" in normalized or "overcast" in normalized:
        return "Nublado"
    if "sun" in normalized:
        return "Ensolarado"
    return clean


def format_weather(city: str, payload: Any) -> tuple[str, str] | None:
    """Monta uma mensagem do Discord em PT-BR e um resumo para leitura local."""
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
    description = translate_weather_condition(value("weatherDesc", "Condição não informada"))
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


async def _fetch_fact_with_throttle(topic: str) -> dict[str, str]:
    global _LAST_FACT_API_CALL
    async with _FACT_API_LOCK:
        loop = asyncio.get_running_loop()
        delay = GLOBAL_FACT_DELAY_SECONDS - (loop.time() - _LAST_FACT_API_CALL)
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            return await asyncio.to_thread(fetch_thematic_fact, topic)
        finally:
            _LAST_FACT_API_CALL = loop.time()


def _user_theme(user_id: int, requested: str | None) -> str:
    topic = normalize_topic(requested) if requested else PREFERENCES.get(user_id, "tema", RANDOM_TOPIC)
    if topic is None:
        raise ValueError("Tema não reconhecido. Use `!temas` para ver as opções.")
    if topic == RANDOM_TOPIC:
        return random.choice(tuple(TOPICS))
    return topic


def _speak_for_user(user_id: int, text: str) -> None:
    voice_choice = PREFERENCES.get(user_id, "voz", "sistema")
    speak(text, voice_choice)


@bot.event
async def on_ready() -> None:
    print(f"Bot conectado como {bot.user}.")
    print("Comandos: !start, !ajuda, !fato, !filosofia, !tema, !temas, !voz, !vozes, !clima <cidade>.")


@bot.command(name="start")
async def start(ctx: commands.Context) -> None:
    await ctx.send(
        "Olá! Sou o bot de curiosidades temáticas e clima.\n"
        "Use `!fato` para receber uma curiosidade falada em português; `!tema ciência`, "
        "`!tema história` ou `!tema astronomia` para escolher o assunto; `!voz feminina` "
        "ou `!voz masculina` para escolher uma voz instalada; `!filosofia` para uma reflexão "
        "separada; e `!clima <cidade>` para consultar o tempo."
    )


@bot.command(name="ajuda", aliases=["help"])
async def help_command(ctx: commands.Context) -> None:
    await ctx.send(
        "**Comandos do bot**\n"
        "`!start` — boas-vindas e resumo.\n"
        "`!fato [ciência|história|astronomia]` — curiosidade temática da Wikipédia em português, lida localmente.\n"
        "`!filosofia [tempo|identidade|teseu|memória|livre-arbítrio|teletransporte]` — reflexão filosófica sob demanda.\n"
        "`!tema [ciência|história|astronomia|aleatório]` — ver ou salvar seu tema preferido.\n"
        "`!temas` — listar temas disponíveis.\n"
        "`!voz [masculina|feminina|sistema]` — salvar sua preferência de voz local.\n"
        "`!vozes` — listar as vozes instaladas no computador que executa o bot.\n"
        "`!clima <cidade>` — previsão atual e leitura local.\n\n"
        "A fala `pyttsx3` sai no computador do bot, não no canal de voz do Discord."
    )


@bot.command(name="temas")
async def themes(ctx: commands.Context) -> None:
    await ctx.send(
        "Temas disponíveis: **Ciência**, **História**, **Astronomia** e **Aleatório**.\n"
        "Escolha com `!tema ciência`, `!tema história`, `!tema astronomia` ou `!tema aleatório`."
    )


@bot.command(name="filosofia", aliases=["reflexao"])
@commands.cooldown(1, 5, commands.BucketType.user)
async def philosophy(ctx: commands.Context, *, assunto: str | None = None) -> None:
    card = choose_philosophy_reflection(assunto)
    if card is None:
        await ctx.send(
            "Não reconheci esse assunto. Tente `!filosofia tempo`, `identidade`, `teseu`, "
            "`memória`, `livre-arbítrio` ou `teletransporte`."
        )
        return
    await ctx.send(format_philosophy_message(card))
    spoken = f"{card['title']}. {card['text']} Pergunta para pensar: {card['question']}"
    await asyncio.to_thread(_speak_for_user, ctx.author.id, spoken)


@bot.command(name="tema")
async def theme(ctx: commands.Context, *, escolha: str | None = None) -> None:
    if escolha is None:
        saved = PREFERENCES.get(ctx.author.id, "tema", RANDOM_TOPIC)
        name = "Aleatório" if saved == RANDOM_TOPIC else TOPICS.get(saved, {}).get("name", "Aleatório")
        await ctx.send(f"Seu tema atual é **{name}**. Altere com `!tema ciência`, `!tema história`, `!tema astronomia` ou `!tema aleatório`.")
        return
    selected = normalize_topic(escolha)
    if selected is None:
        await ctx.send("Não reconheci esse tema. Use `!temas` para ver as opções em português.")
        return
    try:
        PREFERENCES.set(ctx.author.id, "tema", selected)
    except OSError as exc:
        print(f"Não foi possível salvar a preferência de tema ({type(exc).__name__}).")
        await ctx.send("Não consegui salvar sua preferência neste computador.")
        return
    name = "Aleatório" if selected == RANDOM_TOPIC else TOPICS[selected]["name"]
    await ctx.send(f"Pronto! Seu tema agora é **{name}**. Use `!fato` para receber uma curiosidade.")


@bot.command(name="vozes")
async def voices(ctx: commands.Context) -> None:
    try:
        installed = await asyncio.to_thread(list_system_voices)
    except Exception as exc:  # noqa: BLE001  # Os erros do pyttsx3 dependem do mecanismo de voz instalado.
        print(f"Não foi possível consultar as vozes locais ({type(exc).__name__}).")
        await ctx.send("Não consegui consultar as vozes instaladas. Verifique o mecanismo de fala do sistema e o áudio do computador do bot.")
        return
    if not installed:
        await ctx.send("O computador do bot não informou vozes instaladas. Adicione uma voz nas configurações de fala do sistema.")
        return
    lines = [
        f"• {item['name']} — gênero detectado: {item['gender']}; português: {item['portuguese']}"
        for item in installed
    ]
    intro = "**Vozes locais disponíveis** (a detecção de gênero/idioma é aproximada):\n"
    chunks: list[str] = []
    current = intro
    for line in lines:
        if len(current) + len(line) + 1 > 1850:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current:
        chunks.append(current)
    for chunk in chunks:
        await ctx.send(chunk)
    await ctx.send("Para selecionar: `!voz feminina`, `!voz masculina` ou `!voz sistema`. Uma voz PT-BR precisa estar instalada para soar natural em português.")


@bot.command(name="voz")
async def voice(ctx: commands.Context, *, escolha: str | None = None) -> None:
    if escolha is None:
        selected = PREFERENCES.get(ctx.author.id, "voz", "sistema")
        await ctx.send(f"Sua voz atual é **{selected}**. Use `!voz masculina`, `!voz feminina` ou `!voz sistema`. Veja `!vozes` para as vozes instaladas.")
        return
    selected = normalize_voice_choice(escolha)
    if selected == "listar":
        await voices(ctx)
        return
    if selected not in VOICE_CHOICES:
        await ctx.send("Opção inválida. Use `!voz masculina`, `!voz feminina` ou `!voz sistema`.")
        return
    if selected in {"masculina", "feminina"}:
        try:
            available = await asyncio.to_thread(local_voice_available, selected)
        except Exception as exc:  # noqa: BLE001  # Os erros do pyttsx3 dependem do mecanismo de voz instalado.
            print(f"Falha ao listar vozes locais ({type(exc).__name__}).")
            await ctx.send("Não consegui acessar as vozes locais. Confira a instalação do mecanismo de fala.")
            return
        if not available:
            await ctx.send(f"Não encontrei uma voz {selected} detectável neste computador. Use `!vozes` e instale/ative uma voz correspondente no sistema.")
            return
    try:
        PREFERENCES.set(ctx.author.id, "voz", selected)
    except OSError as exc:
        print(f"Não foi possível salvar a preferência de voz ({type(exc).__name__}).")
        await ctx.send("Não consegui salvar sua preferência neste computador.")
        return
    await ctx.send(f"Preferência salva: voz **{selected}**. Ela será usada nos próximos fatos e previsões falados neste computador.")


@bot.command(name="fato", aliases=["fact"])
@commands.cooldown(1, 5, commands.BucketType.user)
async def fact(ctx: commands.Context, *, tema: str | None = None) -> None:
    try:
        selected_topic = _user_theme(ctx.author.id, tema)
    except ValueError as exc:
        await ctx.send(str(exc))
        return
    await ctx.typing()
    try:
        result = await _fetch_fact_with_throttle(selected_topic)
    except WikimediaAPIError as exc:
        if exc.status_code == 429:
            await ctx.send("A Wikipédia pediu uma pausa. Aguarde um pouco e tente novamente.")
        elif exc.status_code == 200:
            await ctx.send("Não encontrei um artigo adequado para esse tema. Tente novamente mais tarde.")
        else:
            await ctx.send(f"A API da Wikipédia respondeu com HTTP {exc.status_code}. Tente novamente depois.")
        print(f"Falha na API Wikimedia: status={exc.status_code}")
        return
    except requests.RequestException as exc:
        print(f"Falha de rede na API Wikimedia ({type(exc).__name__}).")
        await ctx.send("Não consegui acessar a Wikipédia agora. Confira a conexão e tente novamente.")
        return
    except Exception as exc:  # noqa: BLE001  # Uma falha na API não deve encerrar o comando do Discord.
        print(f"Falha inesperada ao buscar curiosidade ({type(exc).__name__}).")
        await ctx.send("Não consegui buscar uma curiosidade agora. Tente novamente mais tarde.")
        return

    message = format_fact_message(result)
    await ctx.send(message)
    await asyncio.to_thread(_speak_for_user, ctx.author.id, result["texto"])


@bot.command(name="clima", aliases=["weather"])
@commands.cooldown(1, 8, commands.BucketType.user)
async def weather(ctx: commands.Context, *, cidade: str) -> None:
    city = " ".join(cidade.split())
    if not city or len(city) > 100:
        await ctx.send("Informe uma cidade com até 100 caracteres. Exemplo: `!clima São Paulo`.")
        return

    url = f"{WEATHER_API_BASE}/{quote(city, safe='')}"
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
    await asyncio.to_thread(_speak_for_user, ctx.author.id, speech)

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
        await ctx.send(f"Canal **{VOICE_CHANNEL_NAME}** pronto, mas não tenho permissão Mover Membros.")
    except discord.HTTPException as exc:
        print(f"Falha ao mover membro ({type(exc).__name__}).")
        await ctx.send("O canal foi preparado, mas o Discord não conseguiu mover você.")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Espere {error.retry_after:.1f} s antes de usar o comando novamente.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Use `!clima <cidade>`. Exemplo: `!clima São Paulo`.")
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

"""Funciones de IA: Groq API + scraping de Goodreads."""
import os
import logging
import random
import re
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]


def _groq_chat(prompt: str, max_tokens: int = 2000, model: str | None = None) -> str | None:
    """Llama a la API de Groq probando modelos en orden hasta obtener respuesta."""
    if not GROQ_API_KEY:
        return None
    models = [model] if model else GROQ_MODELS
    for m in models:
        try:
            body = json.dumps({
                "model": m,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.8,
            }).encode()
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                result = data["choices"][0]["message"]["content"].strip()
                if result:
                    logger.debug("Groq respondió con modelo: %s", m)
                    return result
        except Exception as e:
            logger.warning("Groq error con modelo %s: %s — probando siguiente", m, e)
    return None


def _scrape_goodreads_quotes(book_title: str, author: str = "") -> list[str]:
    """Intenta obtener citas reales de Goodreads para el libro."""
    query = urllib.parse.quote(f"{book_title} {author}".strip())
    url = f"https://www.goodreads.com/quotes/search?q={query}&commit=Search"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Las citas en Goodreads están en <div class="quoteText">
        blocks = re.findall(
            r'class="quoteText"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )
        quotes = []
        for block in blocks:
            # Extraer solo el texto de la cita (antes del <span> del autor)
            text = re.split(r'<span\b', block)[0]
            text = re.sub(r'<[^>]+>', '', text)
            text = text.replace('&#8220;', '"').replace('&#8221;', '"')
            text = text.replace('&ldquo;', '"').replace('&rdquo;', '"')
            text = text.replace('&amp;', '&').replace('&#39;', "'")
            text = re.sub(r'\s+', ' ', text).strip().strip('""\'"\'')
            if 25 < len(text) < 600:
                quotes.append(text)
        return quotes[:8]
    except Exception as e:
        logger.debug("Goodreads scrape failed: %s", e)
        return []


def _scrape_wikiquote_es(book_title: str) -> list[str]:
    """Intenta obtener citas de la Wikipedia en español (Wikiquote)."""
    try:
        title_encoded = urllib.parse.quote(book_title.replace(" ", "_"))
        url = f"https://es.wikiquote.org/wiki/{title_encoded}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Extraer <li> items de las secciones de la página
        items = re.findall(r'<li>(.*?)</li>', html, re.DOTALL)
        quotes = []
        for item in items:
            text = re.sub(r'<[^>]+>', '', item)
            text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
            text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'")
            text = re.sub(r'\s+', ' ', text).strip().strip('""\'"\'«»')
            if 30 < len(text) < 500 and not text.startswith('http'):
                quotes.append(text)
        return quotes[:8]
    except Exception as e:
        logger.debug("Wikiquote ES scrape failed: %s", e)
        return []


def _scrape_citas_in(author: str) -> list[str]:
    """Intenta obtener citas de citas.in para el autor dado."""
    if not author:
        return []
    try:
        # Normalizar nombre del autor: minúsculas, espacios → guiones
        normalized = author.lower().strip()
        normalized = re.sub(r'[áàä]', 'a', normalized)
        normalized = re.sub(r'[éèë]', 'e', normalized)
        normalized = re.sub(r'[íìï]', 'i', normalized)
        normalized = re.sub(r'[óòö]', 'o', normalized)
        normalized = re.sub(r'[úùü]', 'u', normalized)
        normalized = re.sub(r'[ñ]', 'n', normalized)
        normalized = re.sub(r'[^a-z0-9\s-]', '', normalized)
        normalized = re.sub(r'\s+', '-', normalized.strip())
        url = f"https://citas.in/autores/{normalized}/"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Buscar bloques de citas (suelen estar en <p class="cita"> o similares)
        blocks = re.findall(r'class="[^"]*cita[^"]*"[^>]*>(.*?)</[^>]+>', html, re.DOTALL | re.IGNORECASE)
        if not blocks:
            # Intentar extraer párrafos largos como citas
            blocks = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
        quotes = []
        for block in blocks:
            text = re.sub(r'<[^>]+>', '', block)
            text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&#39;', "'")
            text = re.sub(r'\s+', ' ', text).strip().strip('""\'"\'«»')
            if 30 < len(text) < 500:
                quotes.append(text)
        return quotes[:6]
    except Exception as e:
        logger.debug("citas.in scrape failed: %s", e)
        return []


def generate_book_quote(book_title: str, author: str = "") -> str:
    """Obtiene una cita del libro en español. Prueba varias fuentes antes de usar Groq."""
    # 1. Intentar Wikiquote en español
    quotes = _scrape_wikiquote_es(book_title)
    if quotes:
        quote = random.choice(quotes)
        author_credit = f" — {author}" if author else ""
        return f"«{quote}»{author_credit}"

    # 2. Intentar citas.in con el nombre del autor
    if author:
        quotes = _scrape_citas_in(author)
        if quotes:
            quote = random.choice(quotes)
            return f"«{quote}» — {author}"

    # 3. Intentar scraping de Goodreads
    quotes = _scrape_goodreads_quotes(book_title, author)
    if quotes:
        quote = random.choice(quotes)
        author_credit = f" — {author}" if author else ""
        return f"«{quote}»{author_credit}"

    # 4. Fallback: Groq con modelo de mayor calidad
    author_part = f" de {author}" if author else ""
    prompt = (
        f"RESPONDE OBLIGATORIAMENTE EN ESPAÑOL. "
        f"Dame UNA cita real y famosa del libro «{book_title}»{author_part}, "
        f"que sea una frase que realmente aparezca en la traducción española del libro o en español original. "
        f"NO uses inglés ni ningún otro idioma. "
        f"Si no conoces el libro exactamente, da una frase del autor {author or 'desconocido'} de otra obra suya, en español. "
        f"Formato exacto: «[cita textual en español]» — {author or 'Autor'}. Solo la cita, nada más."
    )
    result = _groq_chat(prompt, max_tokens=2000)
    if result:
        return result

    return f"«Los libros son espejos: solo ves en ellos lo que ya llevas dentro.» — Sobre «{book_title}»"


def suggest_book_for_theme(theme: str, pages_hint: int = 500) -> str | None:
    """Sugiere UN libro ideal para el tema dado, preferiblemente en español, ~pages_hint páginas."""
    prompt = (
        f"Eres un experto en clubs de lectura. "
        f"Para la temática '{theme}', sugiere UN SOLO libro que sea ideal para debatir en un club de lectura. "
        f"Requisitos: preferiblemente título en español o traducido al español, "
        f"unas {pages_hint} páginas (entre 300 y 700), "
        f"interesante para debate grupal. "
        f"Responde SOLO con: «Título del libro» de Autor (Año). "
        f"Ejemplo: «El nombre del viento» de Patrick Rothfuss (2007). "
        f"Sin explicaciones adicionales."
    )
    return _groq_chat(prompt, max_tokens=100)


def generate_discussion_questions(book_title: str, author: str = "", synopsis: str = "") -> str:
    """Genera 5 preguntas de debate específicas para el libro."""
    author_part = f" de {author}" if author else ""
    has_synopsis = synopsis and len(synopsis.strip()) > 80

    if has_synopsis:
        synopsis_trimmed = synopsis.strip()[:900]
        prompt = (
            f"Eres un experto facilitador de club de lectura.\n\n"
            f"Libro: «{book_title}»{author_part}\n"
            f"Sinopsis: {synopsis_trimmed}\n\n"
            f"Genera exactamente 5 preguntas de debate profundas y ESPECÍFICAS para este libro. "
            f"Las preguntas deben referirse a personajes, situaciones, temas o momentos concretos "
            f"que aparecen en la sinopsis o son propios de este libro. "
            f"PROHIBIDO hacer preguntas genéricas como '¿Con qué personaje te identificas?' "
            f"o '¿Qué cambiarías del final?'. "
            f"Responde SOLO con las 5 preguntas numeradas, sin introducción. En español."
        )
    else:
        prompt = (
            f"Eres un experto facilitador de club de lectura.\n\n"
            f"Libro: «{book_title}»{author_part}\n\n"
            f"Genera exactamente 5 preguntas de debate profundas y específicas para este libro. "
            f"Basa las preguntas en lo que sabes de la trama, personajes y temas de este libro concreto. "
            f"PROHIBIDO hacer preguntas genéricas aplicables a cualquier libro. "
            f"Responde SOLO con las 5 preguntas numeradas, sin introducción. En español."
        )

    result = _groq_chat(prompt, max_tokens=2000)
    if result:
        return result

    # Fallback con sinopsis si la tenemos
    if has_synopsis:
        fallback = (
            f"Basándote en esta sinopsis de «{book_title}»:\n{synopsis[:500]}\n\n"
            f"Escribe 5 preguntas específicas para debatir en un club de lectura sobre este libro."
        )
        result2 = _groq_chat(fallback, max_tokens=2000)
        if result2:
            return result2

    return (
        f"Preguntas de debate — «{book_title}»\n\n"
        "1. ¿Cuál es el tema central del libro y cómo evoluciona a lo largo de la narración?\n"
        "2. ¿Qué decisión del protagonista te pareció más difícil o controvertida?\n"
        "3. ¿Cómo influye el contexto histórico o social en el desarrollo de la trama?\n"
        "4. ¿Qué simbolismo o metáfora te resultó más significativo?\n"
        "5. ¿Ha cambiado tu perspectiva sobre algún tema después de leer este libro?"
    )

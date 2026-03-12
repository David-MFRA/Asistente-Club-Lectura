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


def _groq_chat(prompt: str, max_tokens: int = 400) -> str | None:
    """Llama a la API de Groq. Devuelve None si no está configurada o hay error."""
    if not GROQ_API_KEY:
        return None
    try:
        body = json.dumps({
            "model": "llama3-8b-8192",
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
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning("Groq API error: %s", e)
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


def generate_book_quote(book_title: str, author: str = "") -> str:
    """Obtiene una cita del libro. Primero intenta Goodreads, luego Groq."""
    # 1. Intentar scraping de Goodreads
    quotes = _scrape_goodreads_quotes(book_title, author)
    if quotes:
        quote = random.choice(quotes)
        author_credit = f" — {author}" if author else ""
        return f"«{quote}»{author_credit}"

    # 2. Fallback: Groq
    author_part = f" de {author}" if author else ""
    prompt = (
        f"Dame UNA cita real y famosa del libro «{book_title}»{author_part}, "
        f"que sea una frase que realmente aparezca en el libro. "
        f"Si no conoces el libro exactamente, di una frase del autor {author} de otra obra suya. "
        f"Formato exacto: «[cita textual]» — {author or 'Autor'}. Solo la cita, nada más."
    )
    result = _groq_chat(prompt, max_tokens=200)
    if result:
        return result

    return f"«Los libros son espejos: solo ves en ellos lo que ya llevas dentro.» — Sobre «{book_title}»"


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

    result = _groq_chat(prompt, max_tokens=600)
    if result:
        return result

    # Fallback con sinopsis si la tenemos
    if has_synopsis:
        fallback = (
            f"Basándote en esta sinopsis de «{book_title}»:\n{synopsis[:500]}\n\n"
            f"Escribe 5 preguntas específicas para debatir en un club de lectura sobre este libro."
        )
        result2 = _groq_chat(fallback, max_tokens=500)
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

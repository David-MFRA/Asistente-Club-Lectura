"""Funciones de IA usando Groq API (modelo llama3-8b-8192)."""
import os
import logging

logger = logging.getLogger(__name__)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


def _groq_chat(prompt: str, max_tokens: int = 400) -> str | None:
    """Llama a la API de Groq. Devuelve None si no está configurada o hay error."""
    if not GROQ_API_KEY:
        return None
    try:
        import urllib.request
        import json
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


def generate_discussion_questions(book_title: str, author: str = "") -> str:
    """Genera 5 preguntas de debate para el club de lectura."""
    author_part = f" de {author}" if author else ""
    prompt = (
        f"Eres un facilitador de club de lectura. Genera exactamente 5 preguntas de debate "
        f"interesantes y reflexivas para el libro «{book_title}»{author_part}. "
        f"Las preguntas deben fomentar la discusión literaria, análisis de personajes y temas. "
        f"Responde SOLO con las 5 preguntas numeradas, sin introducción ni conclusión. En español."
    )
    result = _groq_chat(prompt, max_tokens=500)
    if result:
        return result
    # Fallback: preguntas genéricas
    return (
        f"Preguntas de debate para «{book_title}»:\n\n"
        "1. ¿Qué personaje te resultó más interesante y por qué?\n"
        "2. ¿Qué tema principal te impactó más?\n"
        "3. ¿Cómo te identificaste con el protagonista?\n"
        "4. ¿Qué cambiarías del final?\n"
        "5. ¿A quién recomendarías este libro?"
    )


def generate_book_quote(book_title: str, author: str = "") -> str:
    """Genera o busca una cita inspiradora relacionada con el libro."""
    author_part = f" de {author}" if author else ""
    prompt = (
        f"Genera una cita literaria inspiradora y relevante para el libro «{book_title}»{author_part}. "
        f"Puede ser del propio libro, del autor, o de un libro similar. "
        f"Formato: «[cita]» — [Autor, Obra]. Solo la cita, nada más. En español."
    )
    result = _groq_chat(prompt, max_tokens=200)
    if result:
        return result
    return f"«La lectura es un viaje que nunca termina.» — Sobre «{book_title}»"

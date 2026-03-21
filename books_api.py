import logging
import time
import requests
import html
import re

from deep_translator import GoogleTranslator

logger = logging.getLogger(__name__)

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

REQUEST_TIMEOUT = 8
_RETRY_DELAY = 1.5


# --------------------------------------------------
# UTILIDADES
# --------------------------------------------------

def clean_html(text):
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def traducir(text):
    if not text:
        return ""

    try:
        return GoogleTranslator(
            source="auto",
            target="es"
        ).translate(text)
    except Exception:
        return text


# --------------------------------------------------
# GOOGLE BOOKS
# --------------------------------------------------

def google_books(title):
    """
    Busca libro en Google Books.
    Devuelve datos normalizados compatibles con db.py
    """
    logger.info("Google Books: buscando «%s»", title)

    params = {
        "q": f"intitle:{title}",
        "maxResults": 5,
        "printType": "books"
    }

    data = None
    for attempt in range(2):
        try:
            r = requests.get(
                GOOGLE_BOOKS_URL,
                params=params,
                timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                break
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                logger.warning("Google Books: HTTP %d para «%s», reintentando…", r.status_code, title)
                time.sleep(_RETRY_DELAY)
                continue
            logger.warning("Google Books: HTTP %d para «%s»", r.status_code, title)
            return None
        except Exception:
            if attempt == 0:
                logger.warning("Google Books: error de red buscando «%s», reintentando…", title)
                time.sleep(_RETRY_DELAY)
            else:
                logger.exception("Google Books: error de red buscando «%s»", title)
                return None

    if data is None:
        return None

    items = data.get("items")

    if not items:
        logger.info("Google Books: sin resultados para «%s»", title)
        return None

    v = items[0].get("volumeInfo", {})

    title = v.get("title")

    if not title:
        logger.warning("Google Books: primer resultado sin título para la búsqueda original")
        return None

    authors = v.get("authors") or []

    author = ", ".join(authors) if authors else None

    description = clean_html(v.get("description"))

    language = v.get("language")

    if description and language != "es":
        logger.debug("Google Books: traduciendo descripción (idioma=%s)", language)
        description = traducir(description)

    image_links = v.get("imageLinks") or {}

    cover = (
        image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
    )

    pages = v.get("pageCount")

    logger.info("Google Books: encontrado «%s» de %s (%s págs)", title, author, pages)
    return {
        "title": title.strip(),
        "author": author,
        "description": description,
        "cover": cover,
        "pages": pages,
        "language_code": language,
        "source": "google_books",
        "source_id": items[0].get("id")
    }
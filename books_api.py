import requests
import html
import re

from deep_translator import GoogleTranslator

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

REQUEST_TIMEOUT = 8


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

    try:
        params = {
            "q": f"intitle:{title}",
            "maxResults": 5,
            "printType": "books"
        }

        r = requests.get(
            GOOGLE_BOOKS_URL,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code != 200:
            return None

        data = r.json()

    except Exception:
        return None

    items = data.get("items")

    if not items:
        return None

    v = items[0].get("volumeInfo", {})

    title = v.get("title")

    if not title:
        return None

    authors = v.get("authors") or []

    author = ", ".join(authors) if authors else None

    description = clean_html(v.get("description"))

    language = v.get("language")

    if description and language != "es":
        description = traducir(description)

    image_links = v.get("imageLinks") or {}

    cover = (
        image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
    )

    pages = v.get("pageCount")

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
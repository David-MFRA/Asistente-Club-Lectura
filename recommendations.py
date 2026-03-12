import requests

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

REQUEST_TIMEOUT = 8


def recommend(theme, limit=5):
    """
    Obtiene recomendaciones de libros por temática.
    """

    try:

        params = {
            "q": f"subject:{theme}",
            "maxResults": limit * 2,
            "printType": "books"
        }

        r = requests.get(
            GOOGLE_BOOKS_URL,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        if r.status_code != 200:
            return []

        data = r.json()

    except Exception:
        return []

    items = data.get("items")

    if not items:
        return []

    books = []
    seen = set()

    for item in items:

        v = item.get("volumeInfo", {})

        title = v.get("title")

        if not title:
            continue

        if title in seen:
            continue

        seen.add(title)

        authors = v.get("authors") or []

        author = ", ".join(authors) if authors else "Autor desconocido"

        books.append({
            "title": title,
            "author": author
        })

        if len(books) >= limit:
            break

    return books
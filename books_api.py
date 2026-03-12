import requests
from deep_translator import GoogleTranslator

def traducir(text):

    try:
        return GoogleTranslator(source="auto",target="es").translate(text)
    except:
        return text


def google_books(title):

    url=f"https://www.googleapis.com/books/v1/volumes?q=intitle:{title}"

    r=requests.get(url).json()

    if "items" not in r:
        return None

    v=r["items"][0]["volumeInfo"]

    desc=v.get("description","")

    desc=traducir(desc)

    return {
        "title":v.get("title"),
        "author":",".join(v.get("authors",[])),
        "description":desc,
        "cover":v.get("imageLinks",{}).get("thumbnail","")
    }
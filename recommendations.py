import requests

def recommend(theme):

    url=f"https://www.googleapis.com/books/v1/volumes?q=subject:{theme}"

    r=requests.get(url).json()

    books=[]

    if "items" in r:

        for b in r["items"][:5]:

            books.append(b["volumeInfo"]["title"])

    return books
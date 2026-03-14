import unicodedata

import db


MONTH_NAMES = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12",
}


def normalize_text(text: str) -> str:
    """Normaliza texto: minusculas, sin acentos, sin puntuacion."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def find_meeting_by_text(query: str):
    """Busca la reunion mas relevante por nombre o fecha."""
    meetings = db.get_meetings(limit=20)
    query_norm = normalize_text(query)
    best = None
    best_score = 0

    for meeting in meetings:
        if meeting.get("status") == "closed":
            continue

        name_norm = normalize_text(meeting.get("name", ""))
        if name_norm == query_norm:
            score = 100
        elif query_norm in name_norm:
            score = 80
        else:
            words = query_norm.split()
            matched = sum(1 for word in words if word in name_norm)
            score = int(matched / max(len(words), 1) * 60)

        if meeting.get("final_date"):
            date_str = normalize_text(str(meeting["final_date"]))
            for month_es, month_num in MONTH_NAMES.items():
                if month_es in query_norm and f"-{month_num}-" in date_str:
                    score += 30

        if score > best_score:
            best_score = score
            best = meeting

    return best if best_score >= 30 else None

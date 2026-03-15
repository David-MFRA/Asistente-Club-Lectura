import re
import unicodedata


class InputValidationError(ValueError):
    pass


def _normalize_text(raw_value, *, allow_newlines=False):
    text = unicodedata.normalize("NFKC", str(raw_value or ""))
    filtered = []
    for char in text:
        if char in "\r\n":
            if allow_newlines:
                filtered.append("\n")
            continue
        if char.isprintable():
            filtered.append(char)
    text = "".join(filtered)
    if allow_newlines:
        lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)
    else:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def _validate_length(text, *, field_label, min_length=1, max_length=None):
    if min_length and len(text) < min_length:
        raise InputValidationError(f"{field_label} debe tener al menos {min_length} caracteres.")
    if max_length is not None and len(text) > max_length:
        raise InputValidationError(f"{field_label} no puede superar {max_length} caracteres.")
    return text


def normalize_book_query(raw_value):
    text = _normalize_text(raw_value)
    return _validate_length(text, field_label="El titulo", min_length=2, max_length=120)


def normalize_theme_name(raw_value):
    text = _normalize_text(raw_value)
    return _validate_length(text, field_label="La tematica", min_length=2, max_length=80)


def normalize_bug_description(raw_value):
    text = _normalize_text(raw_value, allow_newlines=True)
    return _validate_length(text, field_label="La descripcion", min_length=8, max_length=1000)


def normalize_admin_search_query(raw_value):
    text = _normalize_text(raw_value)
    return _validate_length(text, field_label="La busqueda", min_length=2, max_length=80)


def truncate_search_query(raw_value):
    return _normalize_text(raw_value)[:80]

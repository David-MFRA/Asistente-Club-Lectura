import re


def esc(text):
    if not text:
        return ""
    return re.sub(r"([_*\[\]()~`>#+=|{}.!\\-])", r"\\\1", str(text))


def bold(text):
    return f"*{esc(text)}*"


def italic(text):
    return f"_{esc(text)}_"


def code(text):
    return f"`{esc(text)}`"

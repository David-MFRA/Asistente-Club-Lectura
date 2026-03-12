import random

# --------------------------------------------------
# PREGUNTAS
# --------------------------------------------------

GENERAL = [
    "¿Quién es el protagonista del libro?",
    "¿Qué personaje secundario te ha gustado más?",
    "¿Qué escena del libro te ha marcado más?",
    "¿Qué parte se te hizo más lenta?",
    "¿Cambiarías el final del libro?",
    "¿Qué personaje te ha resultado más complejo?",
    "¿Qué tema principal crees que trata el libro?",
    "¿Te identificas con algún personaje?",
]

ANALISIS = [
    "¿Qué mensaje intenta transmitir el autor?",
    "¿Cómo evoluciona el protagonista durante la historia?",
    "¿Cuál es el conflicto central del libro?",
    "¿Qué simbolismo encuentras en la obra?",
    "¿Qué crítica social aparece en el libro?",
]

DIVERTIDAS = [
    "¿Qué personaje sobreviviría mejor a un apocalipsis?",
    "¿Qué personaje sería peor compañero de piso?",
    "¿A qué personaje invitarías a cenar?",
    "¿Qué personaje tendría mejor podcast?",
]

# --------------------------------------------------
# GENERADOR
# --------------------------------------------------

def generate():
    """
    Devuelve una pregunta aleatoria para el club de lectura.
    """

    pool = GENERAL + ANALISIS + DIVERTIDAS

    q = random.choice(pool)

    return f"📚 Pregunta para el club:\n\n{q}"
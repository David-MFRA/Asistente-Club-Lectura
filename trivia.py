import random

questions = [

"¿Quién es el protagonista del libro?",
"¿En qué época se ambienta la historia?",
"¿Qué tema principal trata el libro?",
"¿Qué personaje secundario te gusta más?"
]

def generate():

    return random.choice(questions)
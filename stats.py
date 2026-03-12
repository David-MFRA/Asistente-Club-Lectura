import matplotlib.pyplot as plt
import db

def generate():

    data=db.get_votes()

    titles=[d["title"] for d in data]
    votes=[d["votes"] for d in data]

    plt.bar(titles,votes)

    plt.xticks(rotation=45)

    file="stats.png"

    plt.savefig(file)

    return file
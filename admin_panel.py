from flask import Flask,render_template
import db

app=Flask(__name__)

@app.route("/")

def admin():

    books=db.get_books()

    return render_template("admin.html",books=books)
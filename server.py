from flask import *
from flask_socketio import *
from threading import Lock
import random as rng
from os import sys
from subprocess import Popen, PIPE
from enum import *
import re

class State(IntEnum):
    START = auto()
    SELECT = auto()
    REVIEW_FRONT = auto()
    REVIEW_BACK = auto()

lock = Lock()
owner = None
p = None
out = ""
word_lists = []

app = Flask(__name__)
app.secret_key = "1234"
socketio = SocketIO(app)

ansi_escape = re.compile(br'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def read_and_decode(until="\n"):
    global p, out
    until = until.encode()
    n = len(until)
    s = b""
    t = len(s)
    while s[t-n:] != until:
        s += p.stdout.read(1)
        t = len(s)
    out = re.sub(ansi_escape, b'', s).decode().strip()

def send(msg):
    global p
    p.stdin.write(msg.encode())
    p.stdin.flush()

@app.before_request
def check_lock():
    global owner, lock
    if "favicon" in request.base_url: 
        return
    sid = session.get("sid")
    if sid is None:
        sid = rng.randint(0, sys.maxsize)
        session["sid"] = sid
        session["state"] = State.START
    lock.acquire()
    if owner is not None and owner != sid:
        lock.release()
        abort(403)
    owner = sid
    lock.release()

#@socketio.on("disconnect")
def cleanup(wait):
    global p, owner
    if p:
        if wait:
            try: p.wait()
            except: p.kill()
        else:
            p.kill()
    p = None
    owner = None
    session["state"] = State.START

@app.route("/")
def start():
    global p, out
    state = session["state"]
    if state != State.START:
        abort(403)
    if not p:
        p = Popen(["python3", "flashcard.py"], stdout=PIPE, stdin=PIPE)
    read_and_decode("Action: ")
    send("r\n")
    read_and_decode("Select: ")
    session["state"] = State.SELECT
    return render_template("start.html")

@app.route("/select", methods=["GET", "POST"])
def select():
    global out, word_lists
    state = session["state"]
    if state != State.SELECT:
        abort(403)
    if request.method == "POST":
        selected = ",".join(filter(lambda k: k.isdigit(), request.form.keys()))
        if selected:
            send(selected + '\n')
            read_and_decode()
            read_and_decode(": ")
            if out == "Error:":
                tmp = out
                read_and_decode('\n')
                tmp += out
                flash(tmp)
            else:
                n = request.form["number"]
                send(n + '\n')
                read_and_decode("Select: ")
                send('\n')
                session["state"] = State.REVIEW_FRONT
                return redirect("view_front")
        else:
            flash("Error: no word list selected")
    else:
        word_lists = []
        for line in out.split('\n')[:-2]:
            parts = line.split(". ")
            if len(parts) == 1:
                word_lists.append((0, parts[0]))
            else:
                word_lists.append((int(parts[0]), parts[1]))
    return render_template("select.html", word_lists=word_lists)

@app.route("/view_front")
def view_front():
    global out
    state = session["state"]
    if state != State.REVIEW_FRONT:
        abort(403)
    read_and_decode()
    front = out
    if out.find('?') != -1:
        read_and_decode(": ")
        send("n\n")
        session["state"] = State.START
        return redirect("/")
    read_and_decode("[Check] ")
    send('\n')
    session["state"] = State.REVIEW_BACK
    return render_template("front.html", front=front)

@app.route("/view_back", methods=["GET", "POST"])
def view_back():
    global out, p
    state = session["state"]
    if state != State.REVIEW_BACK:
        abort(403)
    if request.method == "POST":
        answer = request.form["submit"]
        send(answer + '\n')
        session["state"] = State.REVIEW_FRONT
        return redirect("view_front")
    read_and_decode('?')
    to = out.rfind('\n')
    back = out[:to]
    read_and_decode(": ")
    return render_template("back.html", back=back)

@app.route("/exit")
def exit():
    send("b\nexit\n")
    return leave(True)

@app.route("/abort")
def leave(wait=False):
    cleanup(wait)
    return "<p>session closed</p>"

if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0")

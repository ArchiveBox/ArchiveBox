from os.path import abspath
from os import getcwd
from pathlib import Path

from bottle import route, run, static_file

@route("/")
def index():
    return "Hello"

@route("/static/<filename>")
def static_path(filename):
    template_path = abspath(getcwd()) / Path("tests/mock_server/templates")
    response = static_file(filename, root=template_path)
    response.set_header("Content-Type", "")
    return response

def start():
    run(host='localhost', port=8080)
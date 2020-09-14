from os.path import abspath
from os import getcwd
from pathlib import Path

from bottle import route, run, static_file, response

@route("/")
def index():
    return "Hello"

@route("/static/<filename>")
def static_path(filename):
    template_path = abspath(getcwd()) / Path("tests/mock_server/templates")
    response = static_file(filename, root=template_path)
    return response

@route("/static_no_content_type/<filename>")
def static_no_content_type(filename):
    template_path = abspath(getcwd()) / Path("tests/mock_server/templates")
    response = static_file(filename, root=template_path)
    response.set_header("Content-Type", "")
    return response

@route("/static/headers/<filename>")
def static_path_with_headers(filename):
    template_path = abspath(getcwd()) / Path("tests/mock_server/templates")
    response = static_file(filename, root=template_path)
    response.add_header("Content-Language", "en")
    response.add_header("Content-Script-Type", "text/javascript")
    response.add_header("Content-Style-Type", "text/css")
    return response

def start():
    run(host='localhost', port=8080)
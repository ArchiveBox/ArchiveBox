from os import getcwd
from pathlib import Path

from bottle import route, run, static_file, response, redirect

@route("/")
def index():
    return "Hello"

@route("/static/<filename>")
def static_path(filename):
    template_path = Path.cwd().resolve() / "tests/mock_server/templates"
    response = static_file(filename, root=template_path)
    return response

@route("/static_no_content_type/<filename>")
def static_no_content_type(filename):
    template_path = Path.cwd().resolve() / "tests/mock_server/templates"
    response = static_file(filename, root=template_path)
    response.set_header("Content-Type", "")
    return response

@route("/static/headers/<filename>")
def static_path_with_headers(filename):
    template_path = Path.cwd().resolve() / "tests/mock_server/templates"
    response = static_file(filename, root=template_path)
    response.add_header("Content-Language", "en")
    response.add_header("Content-Script-Type", "text/javascript")
    response.add_header("Content-Style-Type", "text/css")
    return response

@route("/static/400/<filename>", method="HEAD")
def static_400(filename):
    template_path = Path.cwd().resolve() / "tests/mock_server/templates"
    response = static_file(filename, root=template_path)
    response.status = 400
    response.add_header("Status-Code", "400")
    return response

@route("/static/400/<filename>", method="GET")
def static_200(filename):
    template_path = Path.cwd().resolve() / "tests/mock_server/templates"
    response = static_file(filename, root=template_path)
    response.add_header("Status-Code", "200")
    return response

@route("/redirect/headers/<filename>")
def redirect_to_static(filename):
    redirect(f"/static/headers/$filename")


def start():
    run(host='localhost', port=8080, quiet=True)

from bottle import route, run

@route('/')
def index():
    return "Hello"

def start():
    run(host='localhost', port=8080)
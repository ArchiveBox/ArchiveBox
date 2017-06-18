import sys
from subprocess import run, PIPE

ARCHIVE_PATH = 'bookmarks/archive'


def search_archive(pattern, regex=False):
    args = '-g' if regex else '-Qg'
    ag = run(['ag', args, pattern, ARCHIVE_PATH], stdout=PIPE, stderr=PIPE, timeout=60)
    return (l.decode().replace(ARCHIVE_PATH, '') for l in ag.stdout.splitlines())


def server(port=8080):
    try:
        from flask import Flask
        from flask import request
    except ImportError:
        print('[X] Please install Flask to use the search server: pip install Flask')
        raise SystemExit(1)

    app = Flask('Bookmark Archive')

    @app.route("/search", methods=['GET'])
    def search():
        pattern = request.args.get('search', '')
        use_regex = request.args.get('regex', '')
        return '\n'.join(search_archive(pattern, use_regex))

    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        return response

    app.run(port=port)



if __name__ == '__main__':
    argc = len(sys.argv)
    if '--server' in sys.argv:
        port = sys.argv[2] if argc > 2 else '8080'
        server(port)
    else:
        pattern = sys.argv[2] if argc > 2 else sys.argv[1]
        verbatim = argc > 2  # assumes only possible argument is --exact

        matches = search_archive(pattern, regex=not verbatim)
        print('\n'.join(matches))

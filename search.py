#!/usr/bin/env python3

import sys
from subprocess import run, PIPE, DEVNULL


if run(['which', 'ag'], stderr=DEVNULL).returncode:
    print("[X] Please install ag the silver searcher:\n\t apt install silversearcher-ag\n\t brew install the_silver_searcher")
    raise SystemExit(1)


def search_archive(service, pattern, regex=False):
    args = '-g' if regex else '-Qg'
    archive_path = '{}/archive'.format(service)

    ag = run(['ag', args, pattern, archive_path], stdout=PIPE, stderr=PIPE, timeout=60)
    return (l.decode().replace(archive_path, '') for l in ag.stdout.splitlines())


def server(port=8080):
    try:
        from flask import Flask
        from flask import request
    except ImportError:
        print('[X] Please install Flask to use the search server: pip install Flask')
        raise SystemExit(1)

    app = Flask('Bookmark Archive')

    @app.route("/<service>/search", methods=['GET'])
    def search(service):
        pattern = request.args.get('search', '')
        use_regex = request.args.get('regex', '')
        return '\n'.join(search_archive(service, pattern, use_regex))

    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        return response

    app.run(port=port)



if __name__ == '__main__':
    argc = len(sys.argv)
    if argc == 1 or sys.argv[2] in ('-h', '-v', '--help', 'help'):
        print('Usage:\n\t./search.py --server 8042      # Run a search REST service\n\t./search.py firefox pocket           # search for "firefox" in the pocket archive')
        raise SystemExit(0)

    if '--server' in sys.argv:
        port = sys.argv[2] if argc > 2 else '8042'
        server(port)
    else:
        pattern = sys.argv[2] if argc > 2 else sys.argv[1]
        service = sys.argv[2] if argc > 2 else 'bookmarks'

        matches = search_archive(service, pattern, regex=True)
        print('\n'.join(matches))

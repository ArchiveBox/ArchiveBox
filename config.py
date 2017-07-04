import os
import sys

from subprocess import run, PIPE

# os.getenv('VARIABLE', 'DEFAULT') gets the value of environment
# variable "VARIABLE" and if it is not set, sets it to 'DEFAULT'

# for boolean values, check to see if the string is 'true', and
# if so, the python variable will be True

FETCH_WGET =             os.getenv('FETCH_WGET',             'True'             ).lower() == 'true'
FETCH_WGET_REQUISITES =  os.getenv('FETCH_WGET_REQUISITES',  'True'             ).lower() == 'true'
FETCH_AUDIO =            os.getenv('FETCH_AUDIO',            'False'             ).lower() == 'true'
FETCH_VIDEO =            os.getenv('FETCH_VIDEO',            'False'             ).lower() == 'true'
FETCH_PDF =              os.getenv('FETCH_PDF',              'True'             ).lower() == 'true'
FETCH_SCREENSHOT =       os.getenv('FETCH_SCREENSHOT',       'True'             ).lower() == 'true'
FETCH_FAVICON =          os.getenv('FETCH_FAVICON',          'True'             ).lower() == 'true'
SUBMIT_ARCHIVE_DOT_ORG = os.getenv('SUBMIT_ARCHIVE_DOT_ORG', 'True'             ).lower() == 'true'
RESOLUTION =             os.getenv('RESOLUTION',             '1440,900'         )
ARCHIVE_PERMISSIONS =    os.getenv('ARCHIVE_PERMISSIONS',    '755'              )
CHROME_BINARY =          os.getenv('CHROME_BINARY',          'chromium-browser' )  # change to google-chrome browser if using google-chrome
WGET_BINARY =            os.getenv('WGET_BINARY',            'wget'             )
TIMEOUT =                int(os.getenv('TIMEOUT',            '60'))
INDEX_TEMPLATE =         os.getenv('INDEX_TEMPLATE',         'templates/index.html')
INDEX_ROW_TEMPLATE =     os.getenv('INDEX_ROW_TEMPLATE',     'templates/index_row.html')


def check_dependencies():
    print('[*] Checking Dependencies:')

    python_vers = float('{}.{}'.format(sys.version_info.major, sys.version_info.minor))
    if python_vers < 3.5:
        print('[X] Python version is not new enough: {} (>3.5 is required)'.format(python_vers))
        print('    See https://github.com/pirate/bookmark-archiver#troubleshooting for help upgrading your Python installation.')
        raise SystemExit(1)

    if FETCH_PDF or FETCH_SCREENSHOT:
        if run(['which', CHROME_BINARY]).returncode:
            print('[X] Missing dependency: {}'.format(CHROME_BINARY))
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

        # parse chrome --version e.g. Google Chrome 61.0.3114.0 canary / Chromium 59.0.3029.110 built on Ubuntu, running on Ubuntu 16.04
        result = run([CHROME_BINARY, '--version'], stdout=PIPE)
        version = result.stdout.decode('utf-8').replace('Google Chrome ', '').replace('Chromium ', '').split(' ', 1)[0].split('.', 1)[0]  # TODO: regex might be better
        if int(version) < 59:
            print('[X] Chrome version must be 59 or greater for headless PDF and screenshot saving')
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_WGET:
        if run(['which', 'wget']).returncode:
            print('[X] Missing dependency: wget')
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_FAVICON or SUBMIT_ARCHIVE_DOT_ORG:
        if run(['which', 'curl']).returncode:
            print('[X] Missing dependency: curl')
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

    if FETCH_AUDIO or FETCH_VIDEO:
        if run(['which', 'youtube-dl']).returncode:
            print('[X] Missing dependency: youtube-dl')
            print('    See https://github.com/pirate/bookmark-archiver for help.')
            raise SystemExit(1)

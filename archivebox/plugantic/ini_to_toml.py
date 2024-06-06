from typing import Dict, Any, List

import configparser
import json
import ast

JSONValue = str | bool | int | None | List['JSONValue']

def load_ini_value(val: str) -> JSONValue:
    """Convert lax INI values into strict TOML-compliant (JSON) values"""
    if val.lower() in ('true', 'yes', '1'):
        return True
    if val.lower() in ('false', 'no', '0'):
        return False
    if val.isdigit():
        return int(val)

    try:
        return ast.literal_eval(val)
    except Exception:
        pass

    try:
        return json.loads(val)
    except Exception as err:
        pass
    
    return val


def convert(ini_str: str) -> str:
    """Convert a string of INI config into its TOML equivalent (warning: strips comments)"""

    config = configparser.ConfigParser()
    config.optionxform = str  # capitalize key names
    config.read_string(ini_str)

    # Initialize an empty dictionary to store the TOML representation
    toml_dict = {}

    # Iterate over each section in the INI configuration
    for section in config.sections():
        toml_dict[section] = {}

        # Iterate over each key-value pair in the section
        for key, value in config.items(section):
            parsed_value = load_ini_value(value)

            # Convert the parsed value to its TOML-compatible JSON representation
            toml_dict[section.upper()][key.upper()] = json.dumps(parsed_value)

    # Build the TOML string
    toml_str = ""
    for section, items in toml_dict.items():
        toml_str += f"[{section}]\n"
        for key, value in items.items():
            toml_str += f"{key} = {value}\n"
        toml_str += "\n"

    return toml_str.strip()



### Basic Assertions

test_input = """
[SERVER_CONFIG]
IS_TTY=False
USE_COLOR=False
SHOW_PROGRESS=False
IN_DOCKER=False
IN_QEMU=False
PUID=501
PGID=20
OUTPUT_DIR=/opt/archivebox/data
CONFIG_FILE=/opt/archivebox/data/ArchiveBox.conf
ONLY_NEW=True
TIMEOUT=60
MEDIA_TIMEOUT=3600
OUTPUT_PERMISSIONS=644
RESTRICT_FILE_NAMES=windows
URL_DENYLIST=\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$
URL_ALLOWLIST=None
ADMIN_USERNAME=None
ADMIN_PASSWORD=None
ENFORCE_ATOMIC_WRITES=True
TAG_SEPARATOR_PATTERN=[,]
SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BIND_ADDR=127.0.0.1:8000
ALLOWED_HOSTS=*
DEBUG=False
PUBLIC_INDEX=True
PUBLIC_SNAPSHOTS=True
PUBLIC_ADD_VIEW=False
FOOTER_INFO=Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.
SNAPSHOTS_PER_PAGE=40
CUSTOM_TEMPLATES_DIR=None
TIME_ZONE=UTC
TIMEZONE=UTC
REVERSE_PROXY_USER_HEADER=Remote-User
REVERSE_PROXY_WHITELIST=
LOGOUT_REDIRECT_URL=/
PREVIEW_ORIGINALS=True
LDAP=False
LDAP_SERVER_URI=None
LDAP_BIND_DN=None
LDAP_BIND_PASSWORD=None
LDAP_USER_BASE=None
LDAP_USER_FILTER=None
LDAP_USERNAME_ATTR=None
LDAP_FIRSTNAME_ATTR=None
LDAP_LASTNAME_ATTR=None
LDAP_EMAIL_ATTR=None
LDAP_CREATE_SUPERUSER=False
SAVE_TITLE=True
SAVE_FAVICON=True
SAVE_WGET=True
SAVE_WGET_REQUISITES=True
SAVE_SINGLEFILE=True
SAVE_READABILITY=True
SAVE_MERCURY=True
SAVE_HTMLTOTEXT=True
SAVE_PDF=True
SAVE_SCREENSHOT=True
SAVE_DOM=True
SAVE_HEADERS=True
SAVE_WARC=True
SAVE_GIT=True
SAVE_MEDIA=True
SAVE_ARCHIVE_DOT_ORG=True
RESOLUTION=1440,2000
GIT_DOMAINS=github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht
CHECK_SSL_VALIDITY=True
MEDIA_MAX_SIZE=750m
USER_AGENT=None
CURL_USER_AGENT=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 ArchiveBox/0.8.0 (+https://github.com/ArchiveBox/ArchiveBox/) curl/curl 8.4.0 (x86_64-apple-darwin23.0)
WGET_USER_AGENT=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 ArchiveBox/0.8.0 (+https://github.com/ArchiveBox/ArchiveBox/) wget/GNU Wget 1.24.5
CHROME_USER_AGENT=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 ArchiveBox/0.8.0 (+https://github.com/ArchiveBox/ArchiveBox/)
COOKIES_FILE=None
CHROME_USER_DATA_DIR=None
CHROME_TIMEOUT=0
CHROME_HEADLESS=True
CHROME_SANDBOX=True
CHROME_EXTRA_ARGS=[]
YOUTUBEDL_ARGS=['--restrict-filenames', '--trim-filenames', '128', '--write-description', '--write-info-json', '--write-annotations', '--write-thumbnail', '--no-call-home', '--write-sub', '--write-auto-subs', '--convert-subs=srt', '--yes-playlist', '--continue', '--no-abort-on-error', '--ignore-errors', '--geo-bypass', '--add-metadata', '--format=(bv*+ba/b)[filesize<=750m][filesize_approx<=?750m]/(bv*+ba/b)']
YOUTUBEDL_EXTRA_ARGS=[]
WGET_ARGS=['--no-verbose', '--adjust-extension', '--convert-links', '--force-directories', '--backup-converted', '--span-hosts', '--no-parent', '-e', 'robots=off']
WGET_EXTRA_ARGS=[]
CURL_ARGS=['--silent', '--location', '--compressed']
CURL_EXTRA_ARGS=[]
GIT_ARGS=['--recursive']
SINGLEFILE_ARGS=[]
SINGLEFILE_EXTRA_ARGS=[]
MERCURY_ARGS=['--format=text']
MERCURY_EXTRA_ARGS=[]
FAVICON_PROVIDER=https://www.google.com/s2/favicons?domain={}
USE_INDEXING_BACKEND=True
USE_SEARCHING_BACKEND=True
SEARCH_BACKEND_ENGINE=ripgrep
SEARCH_BACKEND_HOST_NAME=localhost
SEARCH_BACKEND_PORT=1491
SEARCH_BACKEND_PASSWORD=SecretPassword
SEARCH_PROCESS_HTML=True
SONIC_COLLECTION=archivebox
SONIC_BUCKET=snapshots
SEARCH_BACKEND_TIMEOUT=90
FTS_SEPARATE_DATABASE=True
FTS_TOKENIZERS=porter unicode61 remove_diacritics 2
FTS_SQLITE_MAX_LENGTH=1000000000
USE_CURL=True
USE_WGET=True
USE_SINGLEFILE=True
USE_READABILITY=True
USE_MERCURY=True
USE_GIT=True
USE_CHROME=True
USE_NODE=True
USE_YOUTUBEDL=True
USE_RIPGREP=True
CURL_BINARY=curl
GIT_BINARY=git
WGET_BINARY=wget
SINGLEFILE_BINARY=single-file
READABILITY_BINARY=readability-extractor
MERCURY_BINARY=postlight-parser
YOUTUBEDL_BINARY=yt-dlp
NODE_BINARY=node
RIPGREP_BINARY=rg
CHROME_BINARY=chrome
POCKET_CONSUMER_KEY=None
USER=squash
PACKAGE_DIR=/opt/archivebox/archivebox
TEMPLATES_DIR=/opt/archivebox/archivebox/templates
ARCHIVE_DIR=/opt/archivebox/data/archive
SOURCES_DIR=/opt/archivebox/data/sources
LOGS_DIR=/opt/archivebox/data/logs
PERSONAS_DIR=/opt/archivebox/data/personas
URL_DENYLIST_PTN=re.compile('\\.(css|js|otf|ttf|woff|woff2|gstatic\\.com|googleapis\\.com/css)(\\?.*)?$', re.IGNORECASE|re.MULTILINE)
URL_ALLOWLIST_PTN=None
DIR_OUTPUT_PERMISSIONS=755
ARCHIVEBOX_BINARY=/opt/archivebox/.venv/bin/archivebox
VERSION=0.8.0
COMMIT_HASH=102e87578c6036bb0132dd1ebd17f8f05ffc880f
BUILD_TIME=2024-05-15 03:28:05 1715768885
VERSIONS_AVAILABLE=None
CAN_UPGRADE=False
PYTHON_BINARY=/opt/archivebox/.venv/bin/python3.10
PYTHON_ENCODING=UTF-8
PYTHON_VERSION=3.10.14
DJANGO_BINARY=/opt/archivebox/.venv/lib/python3.10/site-packages/django/__init__.py
DJANGO_VERSION=5.0.6 final (0)
SQLITE_BINARY=/opt/homebrew/Cellar/python@3.10/3.10.14/Frameworks/Python.framework/Versions/3.10/lib/python3.10/sqlite3/dbapi2.py
SQLITE_VERSION=2.6.0
CURL_VERSION=curl 8.4.0 (x86_64-apple-darwin23.0)
WGET_VERSION=GNU Wget 1.24.5
WGET_AUTO_COMPRESSION=True
RIPGREP_VERSION=ripgrep 14.1.0
SINGLEFILE_VERSION=None
READABILITY_VERSION=None
MERCURY_VERSION=None
GIT_VERSION=git version 2.44.0
YOUTUBEDL_VERSION=2024.04.09
CHROME_VERSION=Google Chrome 124.0.6367.207
NODE_VERSION=v21.7.3
"""


expected_output = '''[SERVER_CONFIG]
IS_TTY = false
USE_COLOR = false
SHOW_PROGRESS = false
IN_DOCKER = false
IN_QEMU = false
PUID = 501
PGID = 20
OUTPUT_DIR = "/opt/archivebox/data"
CONFIG_FILE = "/opt/archivebox/data/ArchiveBox.conf"
ONLY_NEW = true
TIMEOUT = 60
MEDIA_TIMEOUT = 3600
OUTPUT_PERMISSIONS = 644
RESTRICT_FILE_NAMES = "windows"
URL_DENYLIST = "\\\\.(css|js|otf|ttf|woff|woff2|gstatic\\\\.com|googleapis\\\\.com/css)(\\\\?.*)?$"
URL_ALLOWLIST = null
ADMIN_USERNAME = null
ADMIN_PASSWORD = null
ENFORCE_ATOMIC_WRITES = true
TAG_SEPARATOR_PATTERN = "[,]"
SECRET_KEY = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
BIND_ADDR = "127.0.0.1:8000"
ALLOWED_HOSTS = "*"
DEBUG = false
PUBLIC_INDEX = true
PUBLIC_SNAPSHOTS = true
PUBLIC_ADD_VIEW = false
FOOTER_INFO = "Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests."
SNAPSHOTS_PER_PAGE = 40
CUSTOM_TEMPLATES_DIR = null
TIME_ZONE = "UTC"
TIMEZONE = "UTC"
REVERSE_PROXY_USER_HEADER = "Remote-User"
REVERSE_PROXY_WHITELIST = ""
LOGOUT_REDIRECT_URL = "/"
PREVIEW_ORIGINALS = true
LDAP = false
LDAP_SERVER_URI = null
LDAP_BIND_DN = null
LDAP_BIND_PASSWORD = null
LDAP_USER_BASE = null
LDAP_USER_FILTER = null
LDAP_USERNAME_ATTR = null
LDAP_FIRSTNAME_ATTR = null
LDAP_LASTNAME_ATTR = null
LDAP_EMAIL_ATTR = null
LDAP_CREATE_SUPERUSER = false
SAVE_TITLE = true
SAVE_FAVICON = true
SAVE_WGET = true
SAVE_WGET_REQUISITES = true
SAVE_SINGLEFILE = true
SAVE_READABILITY = true
SAVE_MERCURY = true
SAVE_HTMLTOTEXT = true
SAVE_PDF = true
SAVE_SCREENSHOT = true
SAVE_DOM = true
SAVE_HEADERS = true
SAVE_WARC = true
SAVE_GIT = true
SAVE_MEDIA = true
SAVE_ARCHIVE_DOT_ORG = true
RESOLUTION = [1440, 2000]
GIT_DOMAINS = "github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht"
CHECK_SSL_VALIDITY = true
MEDIA_MAX_SIZE = "750m"
USER_AGENT = null
CURL_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 ArchiveBox/0.8.0 (+https://github.com/ArchiveBox/ArchiveBox/) curl/curl 8.4.0 (x86_64-apple-darwin23.0)"
WGET_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 ArchiveBox/0.8.0 (+https://github.com/ArchiveBox/ArchiveBox/) wget/GNU Wget 1.24.5"
CHROME_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 ArchiveBox/0.8.0 (+https://github.com/ArchiveBox/ArchiveBox/)"
COOKIES_FILE = null
CHROME_USER_DATA_DIR = null
CHROME_TIMEOUT = false
CHROME_HEADLESS = true
CHROME_SANDBOX = true
CHROME_EXTRA_ARGS = []
YOUTUBEDL_ARGS = ["--restrict-filenames", "--trim-filenames", "128", "--write-description", "--write-info-json", "--write-annotations", "--write-thumbnail", "--no-call-home", "--write-sub", "--write-auto-subs", "--convert-subs=srt", "--yes-playlist", "--continue", "--no-abort-on-error", "--ignore-errors", "--geo-bypass", "--add-metadata", "--format=(bv*+ba/b)[filesize<=750m][filesize_approx<=?750m]/(bv*+ba/b)"]
YOUTUBEDL_EXTRA_ARGS = []
WGET_ARGS = ["--no-verbose", "--adjust-extension", "--convert-links", "--force-directories", "--backup-converted", "--span-hosts", "--no-parent", "-e", "robots=off"]
WGET_EXTRA_ARGS = []
CURL_ARGS = ["--silent", "--location", "--compressed"]
CURL_EXTRA_ARGS = []
GIT_ARGS = ["--recursive"]
SINGLEFILE_ARGS = []
SINGLEFILE_EXTRA_ARGS = []
MERCURY_ARGS = ["--format=text"]
MERCURY_EXTRA_ARGS = []
FAVICON_PROVIDER = "https://www.google.com/s2/favicons?domain={}"
USE_INDEXING_BACKEND = true
USE_SEARCHING_BACKEND = true
SEARCH_BACKEND_ENGINE = "ripgrep"
SEARCH_BACKEND_HOST_NAME = "localhost"
SEARCH_BACKEND_PORT = 1491
SEARCH_BACKEND_PASSWORD = "SecretPassword"
SEARCH_PROCESS_HTML = true
SONIC_COLLECTION = "archivebox"
SONIC_BUCKET = "snapshots"
SEARCH_BACKEND_TIMEOUT = 90
FTS_SEPARATE_DATABASE = true
FTS_TOKENIZERS = "porter unicode61 remove_diacritics 2"
FTS_SQLITE_MAX_LENGTH = 1000000000
USE_CURL = true
USE_WGET = true
USE_SINGLEFILE = true
USE_READABILITY = true
USE_MERCURY = true
USE_GIT = true
USE_CHROME = true
USE_NODE = true
USE_YOUTUBEDL = true
USE_RIPGREP = true
CURL_BINARY = "curl"
GIT_BINARY = "git"
WGET_BINARY = "wget"
SINGLEFILE_BINARY = "single-file"
READABILITY_BINARY = "readability-extractor"
MERCURY_BINARY = "postlight-parser"
YOUTUBEDL_BINARY = "yt-dlp"
NODE_BINARY = "node"
RIPGREP_BINARY = "rg"
CHROME_BINARY = "chrome"
POCKET_CONSUMER_KEY = null
USER = "squash"
PACKAGE_DIR = "/opt/archivebox/archivebox"
TEMPLATES_DIR = "/opt/archivebox/archivebox/templates"
ARCHIVE_DIR = "/opt/archivebox/data/archive"
SOURCES_DIR = "/opt/archivebox/data/sources"
LOGS_DIR = "/opt/archivebox/data/logs"
PERSONAS_DIR = "/opt/archivebox/data/personas"
URL_DENYLIST_PTN = "re.compile(\'\\\\.(css|js|otf|ttf|woff|woff2|gstatic\\\\.com|googleapis\\\\.com/css)(\\\\?.*)?$\', re.IGNORECASE|re.MULTILINE)"
URL_ALLOWLIST_PTN = null
DIR_OUTPUT_PERMISSIONS = 755
ARCHIVEBOX_BINARY = "/opt/archivebox/.venv/bin/archivebox"
VERSION = "0.8.0"
COMMIT_HASH = "102e87578c6036bb0132dd1ebd17f8f05ffc880f"
BUILD_TIME = "2024-05-15 03:28:05 1715768885"
VERSIONS_AVAILABLE = null
CAN_UPGRADE = false
PYTHON_BINARY = "/opt/archivebox/.venv/bin/python3.10"
PYTHON_ENCODING = "UTF-8"
PYTHON_VERSION = "3.10.14"
DJANGO_BINARY = "/opt/archivebox/.venv/lib/python3.10/site-packages/django/__init__.py"
DJANGO_VERSION = "5.0.6 final (0)"
SQLITE_BINARY = "/opt/homebrew/Cellar/python@3.10/3.10.14/Frameworks/Python.framework/Versions/3.10/lib/python3.10/sqlite3/dbapi2.py"
SQLITE_VERSION = "2.6.0"
CURL_VERSION = "curl 8.4.0 (x86_64-apple-darwin23.0)"
WGET_VERSION = "GNU Wget 1.24.5"
WGET_AUTO_COMPRESSION = true
RIPGREP_VERSION = "ripgrep 14.1.0"
SINGLEFILE_VERSION = null
READABILITY_VERSION = null
MERCURY_VERSION = null
GIT_VERSION = "git version 2.44.0"
YOUTUBEDL_VERSION = "2024.04.09"
CHROME_VERSION = "Google Chrome 124.0.6367.207"
NODE_VERSION = "v21.7.3"'''


first_output = convert(test_input)      # make sure ini -> toml parses correctly
second_output = convert(first_output)   # make sure toml -> toml parses/dumps consistently
assert first_output == second_output == expected_output  # make sure parsing is indempotent

# # DEBUGGING
# import sys
# import difflib
# sys.stdout.writelines(difflib.context_diff(first_output, second_output, fromfile='first', tofile='second'))
# print(repr(second_output))

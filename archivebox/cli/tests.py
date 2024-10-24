#!/usr/bin/env python3

__package__ = 'archivebox.cli'


import os
import sys
import shutil
import unittest
from pathlib import Path

from contextlib import contextmanager

TEST_CONFIG = {
    'USE_COLOR': 'False',
    'SHOW_PROGRESS': 'False',

    'DATA_DIR': 'data.tests',
    
    'SAVE_ARCHIVE_DOT_ORG': 'False',
    'SAVE_TITLE': 'False',
    
    'USE_CURL': 'False',
    'USE_WGET': 'False',
    'USE_GIT': 'False',
    'USE_CHROME': 'False',
    'USE_YOUTUBEDL': 'False',
}

DATA_DIR = 'data.tests'
os.environ.update(TEST_CONFIG)

from ..main import init
from ..index import load_main_index
from archivebox.config.constants import (
    SQL_INDEX_FILENAME,
    JSON_INDEX_FILENAME,
    HTML_INDEX_FILENAME,
)

from . import (
    archivebox_init,
    archivebox_add,
    archivebox_remove,
)

HIDE_CLI_OUTPUT = True

test_urls = '''
https://example1.com/what/is/happening.html?what=1#how-about-this=1
https://example2.com/what/is/happening/?what=1#how-about-this=1
HTtpS://example3.com/what/is/happening/?what=1#how-about-this=1f
https://example4.com/what/is/happening.html
https://example5.com/
https://example6.com

<test>http://example7.com</test>
[https://example8.com/what/is/this.php?what=1]
[and http://example9.com?what=1&other=3#and-thing=2]
<what>https://example10.com#and-thing=2 "</about>
abc<this["https://subb.example11.com/what/is#and-thing=2?whoami=23&where=1"]that>def
sdflkf[what](https://subb.example12.com/who/what.php?whoami=1#whatami=2)?am=hi
example13.bada
and example14.badb
<or>htt://example15.badc</that>
'''

stdout = sys.stdout
stderr = sys.stderr


@contextmanager
def output_hidden(show_failing=True):
    if not HIDE_CLI_OUTPUT:
        yield
        return

    sys.stdout = open('stdout.txt', 'w+', encoding='utf-8')
    sys.stderr = open('stderr.txt', 'w+', encoding='utf-8')
    try:
        yield
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = stdout
        sys.stderr = stderr
    except Exception:
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = stdout
        sys.stderr = stderr
        if show_failing:
            with open('stdout.txt', 'r', encoding='utf-8') as f:
                print(f.read())
            with open('stderr.txt', 'r', encoding='utf-8') as f:
                print(f.read())
        raise
    finally:
        os.remove('stdout.txt')
        os.remove('stderr.txt')


class TestInit(unittest.TestCase):
    def setUp(self):
        os.makedirs(DATA_DIR, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    def test_basic_init(self):
        with output_hidden():
            archivebox_init.main([])

        assert (Path(DATA_DIR) / SQL_INDEX_FILENAME).exists()
        assert (Path(DATA_DIR) / JSON_INDEX_FILENAME).exists()
        assert (Path(DATA_DIR) / HTML_INDEX_FILENAME).exists()
        assert len(load_main_index(out_dir=DATA_DIR)) == 0

    def test_conflicting_init(self):
        with open(Path(DATA_DIR) / 'test_conflict.txt', 'w+', encoding='utf-8') as f:
            f.write('test')

        try:
            with output_hidden(show_failing=False):
                archivebox_init.main([])
            assert False, 'Init should have exited with an exception'
        except SystemExit:
            pass

        assert not (Path(DATA_DIR) / SQL_INDEX_FILENAME).exists()
        assert not (Path(DATA_DIR) / JSON_INDEX_FILENAME).exists()
        assert not (Path(DATA_DIR) / HTML_INDEX_FILENAME).exists()
        try:
            load_main_index(out_dir=DATA_DIR)
            assert False, 'load_main_index should raise an exception when no index is present'
        except Exception:
            pass

    def test_no_dirty_state(self):
        with output_hidden():
            init()
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        with output_hidden():
            init()


class TestAdd(unittest.TestCase):
    def setUp(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with output_hidden():
            init()

    def tearDown(self):
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    def test_add_arg_url(self):
        with output_hidden():
            archivebox_add.main(['https://getpocket.com/users/nikisweeting/feed/all'])

        all_links = load_main_index(out_dir=DATA_DIR)
        assert len(all_links) == 30

    def test_add_arg_file(self):
        test_file = Path(DATA_DIR) / 'test.txt'
        with open(test_file, 'w+', encoding='utf') as f:
            f.write(test_urls)

        with output_hidden():
            archivebox_add.main([test_file])

        all_links = load_main_index(out_dir=DATA_DIR)
        assert len(all_links) == 12
        os.remove(test_file)

    def test_add_stdin_url(self):
        with output_hidden():
            archivebox_add.main([], stdin=test_urls)

        all_links = load_main_index(out_dir=DATA_DIR)
        assert len(all_links) == 12


class TestRemove(unittest.TestCase):
    def setUp(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with output_hidden():
            init()
            archivebox_add.main([], stdin=test_urls)

    # def tearDown(self):
        # shutil.rmtree(DATA_DIR, ignore_errors=True)


    def test_remove_exact(self):
        with output_hidden():
            archivebox_remove.main(['--yes', '--delete', 'https://example5.com/'])

        all_links = load_main_index(out_dir=DATA_DIR)
        assert len(all_links) == 11

    def test_remove_regex(self):
        with output_hidden():
            archivebox_remove.main(['--yes', '--delete', '--filter-type=regex', r'http(s)?:\/\/(.+\.)?(example\d\.com)'])

        all_links = load_main_index(out_dir=DATA_DIR)
        assert len(all_links) == 4

    def test_remove_domain(self):
        with output_hidden():
            archivebox_remove.main(['--yes', '--delete', '--filter-type=domain', 'example5.com', 'example6.com'])

        all_links = load_main_index(out_dir=DATA_DIR)
        assert len(all_links) == 10

    def test_remove_none(self):
        try:
            with output_hidden(show_failing=False):
                archivebox_remove.main(['--yes', '--delete', 'https://doesntexist.com'])
            assert False, 'Should raise if no URLs match'
        except Exception:
            pass


if __name__ == '__main__':
    if '--verbose' in sys.argv or '-v' in sys.argv:
        HIDE_CLI_OUTPUT = False
    
    unittest.main()

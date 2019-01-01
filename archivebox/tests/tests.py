#!/usr/bin/env python3
import json
import os
from os.path import dirname, pardir, join
from subprocess import check_output, check_call
from tempfile import TemporaryDirectory
from typing import List

import pytest


ARCHIVER_BIN = join(dirname(__file__), pardir, 'archive.py')


class Helper:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def run(self, links, env=None, env_defaults=None):
        if env_defaults is None:
            env_defaults = {
                # we don't wanna spam archive.org witin our tests..
                'SUBMIT_ARCHIVE_DOT_ORG': 'False',
            }
        if env is None:
            env = {}

        env = dict(**env_defaults, **env)

        jj = []
        for url in links:
            jj.append({
                'href': url,
                'description': url,
            })
        input_json = join(self.output_dir, 'input.json')
        with open(input_json, 'w') as fo:
            json.dump(jj, fo)

        if env is None:
            env = {}
        env['OUTPUT_DIR'] = self.output_dir
        check_call(
            [ARCHIVER_BIN, input_json],
            env={**os.environ.copy(), **env},
        )


class TestArchiver:
    def setup(self):
        # self.tdir = TemporaryDirectory(dir='hello')
        class AAA:
            name = 'hello'
        self.tdir = AAA()

    def teardown(self):
        pass
        # self.tdir.cleanup()

    @property
    def output_dir(self):
        return self.tdir.name

    def test_fetch_favicon_false(self):
        h = Helper(self.output_dir)

        h.run(links=[
            'https://google.com',
        ], env={
            'FETCH_FAVICON': 'False',
        })
        # for now no asserts, good enough if it isn't failing

    def test_3000_links(self):
        """
        The pages are deliberatly unreachable. The tool should gracefully process all of them even though individual links are failing.
        """
        h = Helper(self.output_dir)

        h.run(links=[
            f'https://localhost:123/whatever_{i}.html' for i in range(3000)
        ], env={
            'FETCH_FAVICON': 'False',
            'FETCH_SCREENSHOT': 'False',
            'FETCH_PDF': 'False',
            'FETCH_DOM': 'False',
            'CHECK_SSL_VALIDITY': 'False',
        })


if __name__ == '__main__':
    pytest.main([__file__])

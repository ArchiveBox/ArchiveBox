#! /usr/bin/env python3
import os
from setuptools import setup

user_conf_path = os.path.expanduser('~/.config/bookmark-archiver')

setup(
    name='bookmark-archiver',
    version='0.0.3',
    description='Your own personal Way-Back Machine',
    author='Nick Sweeting',
    url='https://pirate.github.io/bookmark-archiver/',
    license='MIT',
    packages=[
        'bookmark_archiver',
    ],
    install_requires=[
        'requests',
    ],
    package_data={
        'configuration':  ['conf/*.conf'],
    },
    data_files=[
        ('/etc/bookmark-archiver', ['conf/archiver.conf']),
        (user_conf_path, ['conf/user.conf']),
    ],
    scripts=[
        'bin/archive',
        'bin/archive-config',
    ],
    zip_safe=False
)

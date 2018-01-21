#! /usr/bin/env python3
import os
from setuptools import setup

user_conf_path = os.path.expanduser('~/.config/bookmark-archiver/archiver.conf')

setup(
    name='bookmark-archiver',
    version='0.0.3',
    description='Your own personal Way-Back Machine',
    author='Nick Sweeting',
    project_urls={
        'website': 'https://pirate.github.io/bookmark-archiver/',
        'repository': 'https://github.com/pirate/bookmark-archiver',
    },
    license='MIT',
    packages=[
        'bookmark_archiver',
    ],
    install_requires=[
        'requests',
    ],
    data_files=[
        ('conf/default.ini', ['/etc/bookmark-archiver/archiver.conf']),
        ('conf/user.ini', [user_conf_path]),
    ],
    scripts=[
        'bin/archive',
    ],
    zip_safe=False
)

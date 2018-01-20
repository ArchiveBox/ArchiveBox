#! /usr/bin/env python3

from setuptools import setup

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
    scripts=[
        'bin/archive',
    ],
    zip_safe=False
)

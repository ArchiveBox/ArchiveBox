#! /usr/bin/env python3
import os
from setuptools import setup, find_packages

user_conf_path = os.path.expanduser('~/.config/bookmark-archiver')

setup(
    name='bookmark-archiver',
    version='0.0.3',
    description='Your own personal Way-Back Machine',
    author='Nick Sweeting',
    url='https://pirate.github.io/bookmark-archiver/',
    license='MIT',
    packages=find_packages(),
    install_requires=[
        'requests',
    ],
    package_data={
        '': [
                'templates/*.html',
                'templates/static/*',
            ],
    },
    data_files=[
        (user_conf_path, ['conf/user.conf']),
    ],
    scripts=[
        'bin/archive',
        'bin/archive-config',
    ],
    zip_safe=False
)

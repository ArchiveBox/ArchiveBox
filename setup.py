import os
import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()


script_dir = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

VERSION = open(os.path.join(script_dir, 'VERSION'), 'r').read().strip()
GIT_HEAD = open(os.path.join(script_dir, '.git', 'HEAD'), 'r').read().strip().split(': ')[1]
GIT_SHA = open(os.path.join(script_dir, '.git', GIT_HEAD), 'r').read().strip()[:9]
PYPI_VERSION = "{}+{}".format(VERSION, GIT_SHA)

with open(os.path.join(script_dir, 'archivebox', 'VERSION'), 'w+') as f:
    f.write(PYPI_VERSION)

setuptools.setup(
    name="archivebox",
    version=PYPI_VERSION,
    author="Nick Sweeting",
    author_email="git@nicksweeting.com",
    description="The self-hosted internet archive.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pirate/ArchiveBox",
    project_urls={
        'Documentation': 'https://github.com/pirate/ArchiveBox/Wiki',
        'Community': 'https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community',
        'Source': 'https://github.com/pirate/ArchiveBox',
        'Bug Tracker': 'https://github.com/pirate/ArchiveBox/issues',
        'Roadmap': 'https://github.com/pirate/ArchiveBox/wiki/Roadmap',
        'Changelog': 'https://github.com/pirate/ArchiveBox/wiki/Changelog',
        'Patreon': 'https://github.com/pirate/ArchiveBox/wiki/Donations',
    },
    packages=setuptools.find_packages(),
    python_requires='>=3.6',
    install_requires=[
        "dataclasses==0.6",
        "base32-crockford==0.3.0",
        "django==2.2",
        "django-extensions==2.1.6",
        "youtube-dl",

        # Some/all of these will likely be added in the future:
        # wpull
        # pywb
        # pyppeteer
        # archivenow
        # requests

    ],
    entry_points={
        'console_scripts': [
            'archivebox = archivebox.__main__:main',
        ],
    },
    package_data={
        'archivebox': ['VERSION', 'templates/*', 'templates/static/*'],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)

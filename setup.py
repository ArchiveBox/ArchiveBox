import os
import setuptools

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
PYTHON_DIR = os.path.join(BASE_DIR, 'archivebox')

with open('README.md', "r") as f:
    README = f.read()

with open(os.path.join(PYTHON_DIR, 'VERSION'), 'r') as f:
    VERSION = f.read().strip()


setuptools.setup(
    name="archivebox",
    version=VERSION,
    author="Nick Sweeting",
    author_email="git@nicksweeting.com",
    description="The self-hosted internet archive.",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/pirate/ArchiveBox",
    license='MIT',
    project_urls={
        'Donate': 'https://github.com/pirate/ArchiveBox/wiki/Donations',
        'Changelog': 'https://github.com/pirate/ArchiveBox/wiki/Changelog',
        'Roadmap': 'https://github.com/pirate/ArchiveBox/wiki/Roadmap',
        'Bug Tracker': 'https://github.com/pirate/ArchiveBox/issues',
        'Source': 'https://github.com/pirate/ArchiveBox',
        'Community': 'https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community',
        'Documentation': 'https://github.com/pirate/ArchiveBox/Wiki',
    },
    packages=setuptools.find_packages(),
    python_requires='>=3.6',
    install_requires=[
        "dataclasses==0.6",
        "mypy-extensions==0.4.1",
        "base32-crockford==0.3.0",
        "django==2.2",
        "django-extensions==2.1.6",
        "python-crontab==2.3.6",
        "youtube-dl",
        "ipython",

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
    include_package_data=True,
    classifiers=[
        "Development Status :: 4 - Beta",

        "Topic :: Utilities",
        "Topic :: System :: Archiving",
        "Topic :: System :: Archiving :: Backup",
        "Topic :: System :: Recovery Tools",
        "Topic :: Sociology :: History",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        "Topic :: Internet :: WWW/HTTP :: WSGI",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Server",
        "Topic :: Software Development :: Libraries :: Python Modules",

        "Intended Audience :: Developers",
        "Intended Audience :: Education",
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Information Technology",
        "Intended Audience :: Legal Industry",
        "Intended Audience :: System Administrators",
        
        "Environment :: Console",
        "Environment :: Web Environment",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        'Framework :: Django',
        "Typing :: Typed",

        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
    ],
)

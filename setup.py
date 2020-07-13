import setuptools
from pathlib import Path

PKG_NAME = "archivebox"
REPO_URL = "https://github.com/pirate/ArchiveBox"
BASE_DIR = Path(__file__).parent.resolve()
SOURCE_DIR = BASE_DIR / PKG_NAME
README = (BASE_DIR / "README.md").read_text()
VERSION = (SOURCE_DIR / "VERSION").read_text().strip()

# To see when setup.py gets called (uncomment for debugging)
# import sys
# print(SOURCE_DIR, f"     (v{VERSION})")
# print('>', sys.executable, *sys.argv)
# raise SystemExit(0)

setuptools.setup(
    name=PKG_NAME,
    version=VERSION,
    license="MIT",
    author="Nick Sweeting",
    author_email="git@nicksweeting.com",
    description="The self-hosted internet archive.",
    long_description=README,
    long_description_content_type="text/markdown",
    url=REPO_URL,
    project_urls={
        "Source":           f"{REPO_URL}",
        "Documentation":    f"{REPO_URL}/wiki",
        "Bug Tracker":      f"{REPO_URL}/issues",
        "Changelog":        f"{REPO_URL}/wiki/Changelog",
        "Roadmap":          f"{REPO_URL}/wiki/Roadmap",
        "Community":        f"{REPO_URL}/wiki/Web-Archiving-Community",
        "Donate":           f"{REPO_URL}/wiki/Donations",
    },
    python_requires=">=3.7",
    install_requires=[
        "requests",
        "atomicwrites",
        "dataclasses==0.6",
        "mypy-extensions==0.4.3",
        "base32-crockford==0.3.0",
        "django==3.0.7",
        "django-extensions==2.2.9",

        "ipython",
        "youtube-dl",
        "python-crontab==2.5.1",
        # "croniter",
        # Some/all of these will likely be added in the future:
        # wpull
        # pywb
        # pyppeteer
        # archivenow
    ],
    extras_require={
        'dev': [
            "setuptools",
            "twine",
            "flake8",
            "ipdb",
            "mypy",
            "django-stubs",
            "sphinx",
            "sphinx-rtd-theme",
            "recommonmark",
            "pytest",
            "bottle",
        ],
        # 'redis': ['redis', 'django-redis'],
        # 'pywb': ['pywb', 'redis'],
    },
    packages=setuptools.find_packages(),
    entry_points={
        "console_scripts": [
            f"{PKG_NAME} = {PKG_NAME}.cli:main",
        ],
    },
    include_package_data=True,
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
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
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Framework :: Django",
        "Typing :: Typed",
    ],
)

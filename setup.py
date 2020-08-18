# import sys
import json
import setuptools

from pathlib import Path
# from subprocess import check_call
# from setuptools.command.install import install
# from setuptools.command.develop import develop
# from setuptools.command.egg_info import egg_info


PKG_NAME = "archivebox"
REPO_URL = "https://github.com/pirate/ArchiveBox"
REPO_DIR = Path(__file__).parent.resolve()
PYTHON_DIR = REPO_DIR / PKG_NAME
README = (PYTHON_DIR / "README.md").read_text()
VERSION = json.loads((PYTHON_DIR / "package.json").read_text().strip())['version']

# To see when setup.py gets called (uncomment for debugging):

# import sys
# print(PYTHON_DIR, f"     (v{VERSION})")
# print('>', sys.executable, *sys.argv)

# Sketchy way to install npm dependencies as a pip post-install script

# def setup_js():
#     if sys.platform.lower() not in ('darwin', 'linux'):
#         sys.stderr.write('[!] Warning: ArchiveBox is not officially supported on this platform.\n')

#     sys.stderr.write(f'[+] Installing ArchiveBox npm package (PYTHON_DIR={PYTHON_DIR})...\n')
#     try:
#         check_call(f'npm install -g "{REPO_DIR}"', shell=True)
#         sys.stderr.write('[√] Automatically installed npm dependencies.\n')
#     except Exception as err:
#         sys.stderr.write(f'[!] Failed to auto-install npm dependencies: {err}\n')
#         sys.stderr.write('     Install NPM/npm using your system package manager, then run:\n')
#         sys.stderr.write('     npm install -g "git+https://github.com/pirate/ArchiveBox.git\n')


# class CustomInstallCommand(install):
#     def run(self):
#         super().run()
#         setup_js()

# class CustomDevelopCommand(develop):
#     def run(self):
#         super().run()
#         setup_js()

# class CustomEggInfoCommand(egg_info):
#     def run(self):
#         super().run()
#         setup_js()

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
        "requests==2.24.0",
        "atomicwrites==1.4.0",
        "mypy-extensions==0.4.3",
        "base32-crockford==0.3.0",
        "django==3.0.8",
        "django-extensions==3.0.3",

        "dateparser",
        "ipython",
        "youtube-dl",
        "python-crontab==2.5.1",
        "croniter==0.3.34",
        "w3lib==1.22.0",
        # Some/all of these will likely be added in the future:
        # wpull
        # pywb
        # pyppeteer
        # archivenow
    ],
    extras_require={
        'dev': [
            "setuptools",
            "wheel",
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
    packages=['archivebox'],
    include_package_data=True,   # see MANIFEST.in
    entry_points={
        "console_scripts": [
            f"{PKG_NAME} = {PKG_NAME}.cli:main",
        ],
    },
    # cmdclass={
    #     'install': CustomInstallCommand,
    #     'develop': CustomDevelopCommand,
    #     'egg_info': CustomEggInfoCommand,
    # },
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

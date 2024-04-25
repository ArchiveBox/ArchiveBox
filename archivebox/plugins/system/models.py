# __package__ = 'archivebox.plugins.system'


import os
import shutil
import sys
import inspect
import django
from sqlite3 import dbapi2 as sqlite3

from pathlib import Path
from typing import List, Dict, Any

from django.db import models
from django.utils.functional import cached_property

from solo.models import SingletonModel

from config import bin_path, bin_version, VERSION

from plugins.defaults.models import ArchiveBoxBaseDependency

ConfigDict = Dict[str, Any]


class BashEnvironmentDependency(ArchiveBoxBaseDependency):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'BASH'
    LABEL = "Bash"
    REQUIRED = True

    PARENT_DEPENDENCIES = []

    BIN_DEPENDENCIES: List[str] = ['bash']
    APT_DEPENDENCIES: List[str] = []
    BREW_DEPENDENCIES: List[str] = []    
    PIP_DEPENDENCIES: List[str] = []
    NPM_DEPENDENCIES: List[str] = []

    DEFAULT_BINARY = 'bash'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = '-c'
    
    ENABLED = models.BooleanField(default=True, editable=not REQUIRED)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)

    VERSION_CMD = models.CharField(max_length=255, default='{BINARY} --version')
    
    # START_CMD = models.CharField(max_length=255, default=DEFAULT_START_CMD)
    # WORKERS = models.IntegerField(default=1)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Shell Environment: bash"
        verbose_name_plural = "Shell Environments: bash"

    # @task
    def install_pkgs(self, os_pkgs=()):
        assert self.is_valid, 'Bash environment is not available on this host'

        for os_dependency in os_pkgs:
            assert bin_path(os_dependency)

        return True

class PythonEnvironmentDependency(ArchiveBoxBaseDependency):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'PYTHON'
    LABEL = "Python"
    REQUIRED = True

    PARENT_DEPENDENCIES = []

    BIN_DEPENDENCIES = ['python3']
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []    
    PIP_DEPENDENCIES = []
    NPM_DEPENDENCIES = []

    DEFAULT_BINARY = 'python3'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = '-c'
    VERSION_CMD = '{BINARY} --version'

    ENABLED = models.BooleanField(default=True, editable=not REQUIRED)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)
    
    # START_CMD = models.CharField(max_length=255, default=DEFAULT_START_CMD)
    # WORKERS = models.IntegerField(default=1)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Shell Environment: python3"

class NodeJSEnvironmentDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'NODEJS'
    LABEL = "NodeJS"
    REQUIRED = True

    PARENT_DEPENDENCIES = []

    BIN_DEPENDENCIES = ['node']
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []    
    PIP_DEPENDENCIES = []
    NPM_DEPENDENCIES = []

    DEFAULT_BINARY = 'node'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = '-c'
    VERSION_CMD = '{BINARY} --version'

    ENABLED = models.BooleanField(default=True, editable=True)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)
    
    # START_CMD = models.CharField(max_length=255, default=DEFAULT_START_CMD)
    # WORKERS = models.IntegerField(default=1)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Shell Environment: node"


class AptEnvironmentDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'APT'
    LABEL = "apt"
    REQUIRED = False

    PARENT_DEPENDENCIES = ['BashEnvironmentDependency']

    BIN_DEPENDENCIES = ['apt-get']
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []
    PIP_PACKAGES = []
    NPM_PACKAGES = []

    DEFAULT_BINARY = 'apt-get'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = '-qq'

    ENABLED = models.BooleanField(default=True, editable=not REQUIRED)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Package Manager: apt"

    # @task
    def install_pkgs(self, apt_pkgs=()):        
        assert self.is_valid, 'Apt environment is not available on this host'

        # with huey.lock_task('apt-install'):

        run(cmd=[self.DEFAULT_BINARY, '-qq', 'update'])
        for apt_package in apt_pkgs:
            run(cmd=[self.DEFAULT_BINARY, 'install', '-y', apt_package])

        return True

class BrewEnvironmentDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'BREW'
    LABEL = "homebrew"
    REQUIRED = False

    PARENT_DEPENDENCIES = ['BashEnvironmentDependency']

    BIN_DEPENDENCIES = ['brew']
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []
    PIP_PACKAGES = []
    NPM_PACKAGES = []

    DEFAULT_BINARY = 'brew'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = ''

    ENABLED = models.BooleanField(default=True, editable=True)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Package Manager: brew"

    # @task
    def install_pkgs(self, brew_pkgs=()):
        assert self.is_valid, 'Brw environment is not available on this host'
        
        run(cmd=[self.DEFAULT_BINARY, 'update'])

        for brew_pkg in brew_pkgs:
            run(cmd=[self.DEFAULT_BINARY, 'install', brew_pkg])

        return True




class PipEnvironmentDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'PIP'
    LABEL = "pip"
    REQUIRED = False

    PARENT_DEPENDENCIES = ['BashEnvironmentDependency']

    BIN_DEPENDENCIES = ['python3', 'pip3']
    APT_DEPENDENCIES = ['python3.11', 'pip3', 'pipx']
    BREW_DEPENDENCIES = ['python@3.11', 'pipx']
    PIP_PACKAGES = ['setuptools', 'pipx']
    NPM_PACKAGES = []

    DEFAULT_BINARY = 'pip3'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = ''
    VERSION_CMD = '{BINARY} --version'

    ENABLED = models.BooleanField(default=True, editable=True)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Package Manager: pip"

    # @task
    def install_pkgs(self, pip_pkgs=()):
        assert self.is_valid, 'Pip environment is not available on this host'
        
        for pip_pkg in pip_pkgs:
            run(cmd=[self.DEFAULT_BINARY, 'install', '--update', '--ignore-installed', pip_pkg])

        return True


class NPMEnvironmentDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'NODEJS'
    LABEL = "NodeJS"
    REQUIRED = False

    PARENT_DEPENDENCIES = ['BashEnvironmentDependency']

    BIN_DEPENDENCIES = ['node', 'npm']
    APT_DEPENDENCIES = ['node', 'npm']
    BREW_DEPENDENCIES = ['node', 'npm']
    PIP_PACKAGES = []
    NPM_PACKAGES = ['npm']

    DEFAULT_BINARY = 'node'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = ''
    VERSION_CMD = '{BINARY} --version'

    ENABLED = models.BooleanField(default=True, editable=True)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Package Manager: npm"

    # @task
    def install_pkgs(self, npm_pkgs=()):
        assert self.is_valid, 'NPM environment is not available on this host'
        
        for npm_pkg in npm_pkgs:
            run(cmd=[self.DEFAULT_BINARY, 'install', npm_pkg])

        return True


class DjangoDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'DJANGO'
    LABEL = "Django"
    REQUIRED = True

    PARENT_DEPENDENCIES = []

    BIN_DEPENDENCIES = ['django-admin.py']
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []
    PIP_PACKAGES = ['django==3.1.14']
    NPM_PACKAGES = []

    DEFAULT_BINARY = 'django-admin.py'
    DEFAULT_START_CMD = 'archivebox server 0.0.0.0:8000'
    DEFAULT_PID_FILE = 'logs/{NAME}_WORKER.pid'
    DEFAULT_STOP_CMD = 'kill "$(<{PID_FILE})"'
    DEFAULT_ARGS = []
    VERSION_CMD = '{BINARY} --version'

    ENABLED = models.BooleanField(default=True, editable=False)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY, editable=False)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS, editable=False)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Internal Dependency: django"

    @cached_property
    def bin_path(self):
        return inspect.getfile(django)

    @cached_property
    def bin_version(self):
        return '.'.join(str(v) for v in django.VERSION[:3])


class SQLiteDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)

    NAME = 'SQLITE'
    LABEL = "SQLite"
    REQUIRED = True

    PARENT_DEPENDENCIES = []

    BIN_DEPENDENCIES = []
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []
    PIP_PACKAGES = []
    NPM_PACKAGES = []

    DEFAULT_BINARY = 'sqlite3'
    DEFAULT_START_CMD = None
    DEFAULT_STOP_CMD = None
    DEFAULT_PID_FILE = None
    DEFAULT_ARGS = []
    VERSION_CMD = 'python3 -c ""'

    ENABLED = models.BooleanField(default=True, editable=False)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY, editable=False)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS, editable=False)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Internal Dependency: sqlite3"

    @cached_property
    def bin_path(self):
        return inspect.getfile(sqlite3)

    @cached_property
    def bin_version(self):
        return sqlite3.version

class ArchiveBoxDependency(ArchiveBoxBaseDependency):
    singleton_instance_id = 1

    id = models.AutoField(primary_key=True)
    
    NAME = 'ARCHIVEBOX'
    LABEL = "ArchiveBox"
    REQUIRED = True

    PARENT_DEPENDENCIES = [
        'PipEnvironmentDependency',
        'DjangoDependency',
        'SQLiteDependency',
    ]

    BIN_DEPENDENCIES = ['archivebox']
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []
    PIP_PACKAGES = ['archivebox']
    NPM_PACKAGES = []

    DEFAULT_BINARY = 'archivebox'
    DEFAULT_START_CMD = '{BINARY} server 0.0.0.0:8000'
    DEFAULT_ARGS = []
    VERSION_CMD = 'archivebox --version'

    ENABLED = models.BooleanField(default=True, editable=False)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY, editable=False)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS, editable=False)

    class Meta:
        abstract = False
        app_label = 'system'
        verbose_name = "Internal Dependency: archivebox"

    @cached_property
    def bin_path(self):
        return sys.argv[0] or bin_path('archivebox')

    @cached_property
    def bin_version(self):
        # return config['VERSION']
        return VERSION


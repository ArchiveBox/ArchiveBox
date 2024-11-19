__package__ = 'archivebox.core'

from rich.console import Console

# helpful imports that make the shell easier to work with out-of-the-box:
import re                                  # noqa
import os                                  # noqa
import sys                                 # noqa
import json                                # noqa
import psutil                              # noqa
import django                              # noqa
import pydantic                            # noqa
import requests                            # noqa
import subprocess                          # noqa
import archivebox                          # noqa
import abx                                 # noqa
from benedict import benedict              # noqa
from django.utils import timezone          # noqa
from datetime import datetime, timedelta   # noqa
from django.conf import settings           # noqa

from archivebox import CONSTANTS           # noqa
from archivebox.cli import *               # noqa

CONFIG = archivebox.pm.hook.get_FLAT_CONFIG()

if __name__ == '__main__':
    # load the rich extension for ipython for pretty printing
    # https://rich.readthedocs.io/en/stable/introduction.html#ipython-extension
    get_ipython().run_line_magic('load_ext', 'rich')         # type: ignore # noqa

    # prnt = print with cropping using ... ellipsis for helptext that doens't matter that much
    console = Console()
    prnt = lambda *args, **kwargs: console.print(*args, overflow='ellipsis', soft_wrap=True, **kwargs)


    # print the welcome message
    prnt('[green]import re, os, sys, psutil, subprocess, reqiests, json, pydantic, benedict, django, abx[/]')
    prnt('[yellow4]# ArchiveBox Imports[/]')
    prnt('[yellow4]import archivebox[/]')
    prnt('[yellow4]from archivebox.cli import *[/]')
    prnt()
    
    if console.width >= 80:
        from archivebox.misc.logging import rainbow
        prnt(rainbow(archivebox.ASCII_LOGO))
        
    prnt('[i] :heavy_dollar_sign: Welcome to the ArchiveBox Shell!')
    prnt('    [deep_sky_blue4]Docs:[/deep_sky_blue4] [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Shell-Usage]https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Shell-Usage[/link]')
    prnt('          [link=https://docs.archivebox.io/en/dev/apidocs/archivebox/archivebox.html]https://docs.archivebox.io/en/dev/apidocs/archivebox/archivebox.html[/link]')
    prnt()
    prnt(' :grey_question: [violet]Hint[/] [i]Here are some examples to get started:[/]')
    prnt('    add[blink][deep_sky_blue4]?[/deep_sky_blue4][/blink]                                                                        [grey53]# add ? after anything to get help[/]')
    prnt('    add("https://example.com/some/new/url")                                     [grey53]# call CLI methods from the shell[/]')
    prnt('    snap = Snapshot.objects.filter(url__contains="https://example.com").last()  [grey53]# query for individual snapshots[/]')
    prnt('    snap.archiveresult_set.all()                                                [grey53]# see extractor results[/]')
    prnt('    bool(re.compile(CONFIG.URL_DENYLIST).search("https://example.com/abc.exe")) [grey53]# test out a config change[/]')

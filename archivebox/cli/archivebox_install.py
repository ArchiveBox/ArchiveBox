#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import os
import sys
from typing import Optional, List

import rich_click as click
from rich import print

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def install(binproviders: Optional[List[str]]=None, binaries: Optional[List[str]]=None, dry_run: bool=False) -> None:
    """Automatically install all ArchiveBox dependencies and extras"""
    
    # if running as root:
    #    - run init to create index + lib dir
    #    - chown -R 911 DATA_DIR
    #    - install all binaries as root
    #    - chown -R 911 LIB_DIR
    # else:
    #    - run init to create index + lib dir as current user
    #    - install all binaries as current user
    #    - recommend user re-run with sudo if any deps need to be installed as root

    import abx
    import archivebox
    from archivebox.config.permissions import IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, SudoPermission
    from archivebox.config.paths import DATA_DIR, ARCHIVE_DIR, get_or_create_working_lib_dir
    from archivebox.misc.logging import stderr
    from archivebox.cli.archivebox_init import init
    from archivebox.misc.system import run as run_shell


    if not (os.access(ARCHIVE_DIR, os.R_OK) and ARCHIVE_DIR.is_dir()):
        init()  # must init full index because we need a db to store InstalledBinary entries in

    print('\n[green][+] Installing ArchiveBox dependencies automatically...[/green]')
    
    # we never want the data dir to be owned by root, detect owner of existing owner of DATA_DIR to try and guess desired non-root UID
    if IS_ROOT:
        EUID = os.geteuid()
        
        # if we have sudo/root permissions, take advantage of them just while installing dependencies
        print()
        print(f'[yellow]:warning:  Running as UID=[blue]{EUID}[/blue] with [red]sudo[/red] only for dependencies that need it.[/yellow]')
        print(f'    DATA_DIR, LIB_DIR, and TMP_DIR will be owned by [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue].')
        print()
    
    LIB_DIR = get_or_create_working_lib_dir()
    
    package_manager_names = ', '.join(
        f'[yellow]{binprovider.name}[/yellow]'
        for binprovider in reversed(list(abx.as_dict(abx.pm.hook.get_BINPROVIDERS()).values()))
        if not binproviders or (binproviders and binprovider.name in binproviders)
    )
    print(f'[+] Setting up package managers {package_manager_names}...')
    for binprovider in reversed(list(abx.as_dict(abx.pm.hook.get_BINPROVIDERS()).values())):
        if binproviders and binprovider.name not in binproviders:
            continue
        try:
            binprovider.setup()
        except Exception:
            # it's ok, installing binaries below will automatically set up package managers as needed
            # e.g. if user does not have npm available we cannot set it up here yet, but once npm Binary is installed
            # the next package that depends on npm will automatically call binprovider.setup() during its own install
            pass
    
    print()
    
    for binary in reversed(list(abx.as_dict(abx.pm.hook.get_BINARIES()).values())):
        if binary.name in ('archivebox', 'django', 'sqlite', 'python'):
            # obviously must already be installed if we are running
            continue
        
        if binaries and binary.name not in binaries:
            continue
        
        providers = ' [grey53]or[/grey53] '.join(
            provider.name for provider in binary.binproviders_supported
            if not binproviders or (binproviders and provider.name in binproviders)
        )
        if not providers:
            continue
        print(f'[+] Detecting / Installing [yellow]{binary.name.ljust(22)}[/yellow] using [red]{providers}[/red]...')
        try:
            with SudoPermission(uid=0, fallback=True):
                # print(binary.load_or_install(fresh=True).model_dump(exclude={'overrides', 'bin_dir', 'hook_type'}))
                if binproviders:
                    providers_supported_by_binary = [provider.name for provider in binary.binproviders_supported]
                    for binprovider_name in binproviders:
                        if binprovider_name not in providers_supported_by_binary:
                            continue
                        try:
                            if dry_run:
                                # always show install commands when doing a dry run
                                sys.stderr.write("\033[2;49;90m")  # grey53
                                result = binary.install(binproviders=[binprovider_name], dry_run=dry_run).model_dump(exclude={'overrides', 'bin_dir', 'hook_type'})
                                sys.stderr.write("\033[00m\n")     # reset
                            else:
                                loaded_binary = archivebox.pm.hook.binary_load_or_install(binary=binary, binproviders=[binprovider_name], fresh=True, dry_run=dry_run, quiet=False)
                                result = loaded_binary.model_dump(exclude={'overrides', 'bin_dir', 'hook_type'})
                            if result and result['loaded_version']:
                                break
                        except Exception as e:
                            print(f'[red]:cross_mark: Failed to install {binary.name} as using {binprovider_name} as user {ARCHIVEBOX_USER}: {e}[/red]')
                else:
                    if dry_run:
                        sys.stderr.write("\033[2;49;90m")  # grey53
                        binary.install(dry_run=dry_run).model_dump(exclude={'overrides', 'bin_dir', 'hook_type'})
                        sys.stderr.write("\033[00m\n")  # reset
                    else:
                        loaded_binary = archivebox.pm.hook.binary_load_or_install(binary=binary, fresh=True, dry_run=dry_run)
                        result = loaded_binary.model_dump(exclude={'overrides', 'bin_dir', 'hook_type'})
            if IS_ROOT and LIB_DIR:
                with SudoPermission(uid=0):
                    if ARCHIVEBOX_USER == 0:
                        os.system(f'chmod -R 777 "{LIB_DIR.resolve()}"')
                    else:    
                        os.system(f'chown -R {ARCHIVEBOX_USER} "{LIB_DIR.resolve()}"')
        except Exception as e:
            print(f'[red]:cross_mark: Failed to install {binary.name} as user {ARCHIVEBOX_USER}: {e}[/red]')
            if binaries and len(binaries) == 1:
                # if we are only installing a single binary, raise the exception so the user can see what went wrong
                raise
                
    from archivebox.config.django import setup_django
    setup_django()
    
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if not User.objects.filter(is_superuser=True).exclude(username='system').exists():
        stderr('\n[+] Don\'t forget to create a new admin user for the Web UI...', color='green')
        stderr('    archivebox manage createsuperuser')
        # run_subcommand('manage', subcommand_args=['createsuperuser'], pwd=out_dir)
    
    print('\n[green][√] Set up ArchiveBox and its dependencies successfully.[/green]\n', file=sys.stderr)
    
    from abx_plugin_pip.binaries import ARCHIVEBOX_BINARY
    
    extra_args = []
    if binproviders:
        extra_args.append(f'--binproviders={",".join(binproviders)}')
    if binaries:
        extra_args.append(f'--binaries={",".join(binaries)}')
    
    proc = run_shell([ARCHIVEBOX_BINARY.load().abspath, 'version', *extra_args], capture_output=False, cwd=DATA_DIR)
    raise SystemExit(proc.returncode)


@click.command()
@click.option('--binproviders', '-p', type=str, help='Select binproviders to use DEFAULT=env,apt,brew,sys_pip,venv_pip,lib_pip,pipx,sys_npm,lib_npm,puppeteer,playwright (all)', default=None)
@click.option('--binaries', '-b', type=str, help='Select binaries to install DEFAULT=curl,wget,git,yt-dlp,chrome,single-file,readability-extractor,postlight-parser,... (all)', default=None)
@click.option('--dry-run', '-d', is_flag=True, help='Show what would be installed without actually installing anything', default=False)
@docstring(install.__doc__)
def main(**kwargs) -> None:
    install(**kwargs)
    

if __name__ == '__main__':
    main()

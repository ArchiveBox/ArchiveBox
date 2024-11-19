__package__ = 'archivebox.cli'
__command__ = 'archivebox'
import os
import sys
from importlib import import_module

import rich_click as click
from rich import print

from archivebox.config.version import VERSION



if '--debug' in sys.argv:
    os.environ['DEBUG'] = 'True'
    sys.argv.remove('--debug')


class ArchiveBoxGroup(click.Group):
    """lazy loading click group for archivebox commands"""
    meta_commands = {
        'help': 'archivebox.cli.archivebox_help.main',
        'version': 'archivebox.cli.archivebox_version.main',
    }
    setup_commands = {
        'init': 'archivebox.cli.archivebox_init.main',
        'install': 'archivebox.cli.archivebox_install.main',
    }
    archive_commands = {
        'add': 'archivebox.cli.archivebox_add.main',
        'remove': 'archivebox.cli.archivebox_remove.main',
        'update': 'archivebox.cli.archivebox_update.main',
        'search': 'archivebox.cli.archivebox_search.main',
        'status': 'archivebox.cli.archivebox_status.main',
        'config': 'archivebox.cli.archivebox_config.main',
        'schedule': 'archivebox.cli.archivebox_schedule.main',
        'server': 'archivebox.cli.archivebox_server.main',
        'shell': 'archivebox.cli.archivebox_shell.main',
        'manage': 'archivebox.cli.archivebox_manage.main',
    }
    all_subcommands = {
        **meta_commands,
        **setup_commands,
        **archive_commands,
    }
    renamed_commands = {
        'setup': 'install',
        'list': 'search',
        'import': 'add',
        'archive': 'add',
        'export': 'search',
    }
    

    def get_command(self, ctx, cmd_name):
        # handle renamed commands
        if cmd_name in self.renamed_commands:
            new_name = self.renamed_commands[cmd_name]
            print(f' [violet]Hint:[/violet] `archivebox {cmd_name}` has been renamed to `archivebox {new_name}`')
            cmd_name = new_name
            ctx.invoked_subcommand = cmd_name
        
        # handle lazy loading of commands
        if cmd_name in self.all_subcommands:
            return self._lazy_load(cmd_name)
        
        # fall-back to using click's default command lookup
        return super().get_command(ctx, cmd_name)

    @classmethod
    def _lazy_load(cls, cmd_name):
        import_path = cls.all_subcommands[cmd_name]
        modname, funcname = import_path.rsplit('.', 1)
        
        # print(f'LAZY LOADING {import_path}')
        mod = import_module(modname)
        func = getattr(mod, funcname)
        
        if not hasattr(func, '__doc__'):
            raise ValueError(f'lazy loading of {import_path} failed - no docstring found on method')
        
        # if not isinstance(cmd, click.BaseCommand):
            # raise ValueError(f'lazy loading of {import_path} failed - not a click command')
            
        return func


@click.group(cls=ArchiveBoxGroup, invoke_without_command=True)
@click.option('--help', '-h', is_flag=True, help='Show help')
@click.version_option(VERSION, '-v', '--version', package_name='archivebox', message='%(version)s')
@click.pass_context
def cli(ctx, help=False):
    """ArchiveBox: The self-hosted internet archive"""
    
    # if --help is passed or no subcommand is given, show custom help message
    if help or ctx.invoked_subcommand is None:
        ctx.invoke(ctx.command.get_command(ctx, 'help'))
    
    # if the subcommand is in the archive_commands dict and is not 'manage',
    # then we need to set up the django environment and check that we're in a valid data folder
    if ctx.invoked_subcommand in ArchiveBoxGroup.archive_commands and ctx.invoked_subcommand != 'manage':
        # print('SETUP DJANGO AND CHECK DATA FOLDER')
        from archivebox.config.django import setup_django
        from archivebox.misc.checks import check_data_folder
        setup_django()
        check_data_folder()

def main(args=None, prog_name=None):
    # show `docker run archivebox xyz` in help messages if running in docker
    IN_DOCKER = os.environ.get('IN_DOCKER', False) in ('1', 'true', 'True', 'TRUE', 'yes')
    prog_name = prog_name or ('docker compose run archivebox' if IN_DOCKER else 'archivebox')

    try:
        cli(args=args, prog_name=prog_name)
    except KeyboardInterrupt:
        print('\n\n[red][X] Got CTRL+C. Exiting...[/red]')


if __name__ == '__main__':
    main()

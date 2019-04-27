from cli import list_subcommands

from .config import ANSI


if __name__ == '__main__':
    print('{green}# ArchiveBox Imports{reset}'.format(**ANSI))
    # print('from archivebox.core.models import Page, User')
    print('{green}from archivebox.cli import\narchivebox_{}{reset}'.format("\narchivebox_".join(list_subcommands().keys()), **ANSI))
    print()
    print('[i] Welcome to the ArchiveBox Shell! Example use:')
    print('    print(Page.objects.filter(is_archived=True).count())')
    print('    Page.objects.get(url="https://example.com").as_json()')

    print('    Page.objects.get(url="https://example.com").as_json()')

    print('    from archivebox.main import get_invalid_folders')

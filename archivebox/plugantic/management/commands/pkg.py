__package__ = 'archivebox.plugantic.management.commands'

from django.core.management.base import BaseCommand
from django.conf import settings

from pydantic_pkgr import Binary, BinProvider, BrewProvider, EnvProvider, SemVer
from pydantic_pkgr.binprovider import bin_abspath

from ....config import NODE_BIN_PATH, bin_path
from ...base_binary import env


class Command(BaseCommand):
    def handle(self, *args, method, **options):
        method(*args, **options)

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(title="sub-commands", required=True)

        list_parser = subparsers.add_parser("list", help="List archivebox runtime dependencies.")
        list_parser.set_defaults(method=self.list)

        install_parser = subparsers.add_parser("install", help="Install archivebox runtime dependencies.")
        install_parser.add_argument("--update", action="store_true", help="Update dependencies to latest versions.")
        install_parser.add_argument("package_names", nargs="+", type=str)
        install_parser.set_defaults(method=self.install)

    def list(self, *args, **options):
        self.stdout.write('################# PLUGINS ####################')
        for plugin in settings.PLUGINS.values():
            self.stdout.write(f'{plugin.name}:')
            for binary in plugin.binaries:
                try:
                    binary = binary.load()
                except Exception as e:
                    # import ipdb; ipdb.set_trace()
                    raise
                self.stdout.write(f'    {binary.name.ljust(14)} {str(binary.version).ljust(11)} {binary.binprovider.INSTALLER_BIN.ljust(5)}  {binary.abspath}')

        self.stdout.write('\n################# LEGACY ####################')
        for bin_key, dependency in settings.CONFIG.DEPENDENCIES.items():
            bin_name = settings.CONFIG[bin_key]

            self.stdout.write(f'{bin_key}:     {bin_name}')

            # binary = Binary(name=package_name, providers=[env])
            # print(binary)

            # try:
            #     loaded_bin = binary.load()
            #     self.stdout.write(
            #         self.style.SUCCESS(f'Successfully loaded {package_name}:') + str(loaded_bin)
            #     )
            # except Exception as e:
            #     self.stderr.write(
            #         self.style.ERROR(f"Error loading {package_name}: {e}")
            #     )

    def install(self, *args, bright, **options):
        for package_name in options["package_names"]:
            binary = Binary(name=package_name, providers=[env])
            print(binary)

            try:
                loaded_bin = binary.load()
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully loaded {package_name}:') + str(loaded_bin)
                )
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"Error loading {package_name}: {e}")
                )

"""
LDAP Configuration Validation Hook

This hook validates that all required LDAP configuration options are set
when LDAP_ENABLED=True.
"""

__package__ = 'archivebox.plugins.ldap'

import sys
from typing import Dict, Any


REQUIRED_LDAP_SETTINGS = [
    'LDAP_SERVER_URI',
    'LDAP_BIND_DN',
    'LDAP_BIND_PASSWORD',
    'LDAP_USER_BASE',
]


def on_Config__00_ldap_validate(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate LDAP configuration when LDAP is enabled.

    This hook runs during config loading to ensure all required LDAP
    settings are provided when LDAP_ENABLED=True.
    """
    ldap_enabled = config.get('LDAP_ENABLED', False)

    # Convert string to bool if needed
    if isinstance(ldap_enabled, str):
        ldap_enabled = ldap_enabled.lower() in ('true', 'yes', '1')

    if not ldap_enabled:
        # LDAP not enabled, no validation needed
        return config

    # Check if all required settings are provided
    missing_settings = []
    for setting in REQUIRED_LDAP_SETTINGS:
        value = config.get(setting, '')
        if not value or value == '':
            missing_settings.append(setting)

    if missing_settings:
        from rich.console import Console
        console = Console(stderr=True)
        console.print('[red][X] Error:[/red] LDAP_* config options must all be set if LDAP_ENABLED=True')
        console.print('[red]Missing:[/red]')
        for setting in missing_settings:
            console.print(f'  - {setting}')
        console.print()
        console.print('[yellow]Hint:[/yellow] Set these values in ArchiveBox.conf or via environment variables:')
        for setting in missing_settings:
            console.print(f'  export {setting}="your_value_here"')
        sys.exit(1)

    return config

"""
LDAP authentication module for ArchiveBox.

This module provides native LDAP authentication support using django-auth-ldap.
It only activates if:
1. LDAP_ENABLED=True in config
2. Required LDAP libraries (python-ldap, django-auth-ldap) are installed

To install LDAP dependencies:
    pip install archivebox[ldap]

Or manually:
    apt install build-essential python3-dev libsasl2-dev libldap2-dev libssl-dev
    pip install python-ldap django-auth-ldap
"""

__package__ = "archivebox.ldap"

.. sidebar:: Welcome to ArchiveBox!
    
    Just getting started?
        Check out the `Quickstart <Quickstart.html>`_ guide.
    Need help with something?
        Open an issue on `Github <https://github.com/ArchiveBox/ArchiveBox/issues>`_ or chat on `Zulip <https://zulip.archivebox.io>`_.
    Want to join the community?
        See our `Community Wiki <https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community>`_ page.

    .. image:: logo.png
        :width: 200px
        :align: center
        :alt: ArchiveBox Logo

==========
ArchiveBox
==========

    "The open-source self-hosted internet archive."

`Website <https://archivebox.io>`_ | `Github <https://github.com/ArchiveBox/ArchiveBox>`_ | `Source <https://github.com/ArchiveBox/ArchiveBox/tree/dev>`_ | `Bug Tracker <https://github.com/ArchiveBox/ArchiveBox/issues>`_

.. code-block:: bash
    
    mkdir my-archive; cd my-archive/
    uv tool install --python 3.13 --prerelease explicit --upgrade 'archivebox>=0.9.0rc0,<0.10'

    archivebox init
    archivebox install
    archivebox add https://example.com
    archivebox status


=============
Documentation
=============

.. toctree::
    :maxdepth: 2
    
    Contents.rst

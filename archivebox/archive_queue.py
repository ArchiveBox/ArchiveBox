# ArchiveBox
# MatthewJohn 2019 | MIT License
# https://github.com/matthewjohn/ArchiveBox

import os
from threading import Thread
from time import sleep

from archive import load_links, update_archive
from index import (
    write_links_index,
)
from config import (
    ONLY_NEW,
    OUTPUT_DIR,
)
from util import (
    save_stdin_source,
    migrate_data,
)


class ArchiveQueue(object):
    """Provide a queueing system between web interface and archiving agent."""

    # List of queued links to be processed.
    QUEUE = []

    @classmethod
    def add_link_to_queue(cls, link):
        """Add link to be queued to proccessed."""
        ArchiveQueue.QUEUE.append(link)

    @classmethod
    def get_link(cls):
        """Obtain a link, or return None is quee is empty."""
        return ArchiveQueue.QUEUE.pop(0) if len(ArchiveQueue.QUEUE) else None


class ArchiveAgent(Thread):
    """Threaded agent to perform archving."""

    # Class variable to store singleton instance.
    INSTANCE = None

    # Cached reference to 'old links'
    OLD_LINKS = None

    @classmethod
    def get_instance(cls):
        """Return singleton instance of thread."""
        if cls.INSTANCE is None:
            cls.INSTANCE = cls()

        return cls.INSTANCE

    def __init__(self):
        """Store member variable for starting/stopping."""
        self.stop = False
        super(ArchiveAgent, self).__init__()

    def run(self):
        """Method for thread loop."""

        migrate_data()

        # See if archive folder [already exists
        for out_dir in (OUTPUT_DIR, 'bookmarks', 'pocket', 'pinboard', 'html'):
            if os.path.exists(out_dir):
                break
        else:
            out_dir = OUTPUT_DIR
        resume = None

        # Continue looping until stopped
        while not self.stop:

            link = ArchiveQueue.get_link()

            if link is None:
                # If no link is returned, the queue is empty, so
                # wait and iterate again
                sleep(5)
                continue

            print('Processing %s' % link)

            source = save_stdin_source(link)

            # Step 1: Parse the links and dedupe them with existing archive
            all_links, new_links = load_links(archive_path=out_dir,
                                              import_path=source)

            # Step 2: Write new index
            write_links_index(out_dir=out_dir, links=all_links)

            # Step 3: Run the archive methods for each link
            if ONLY_NEW:
                update_archive(out_dir, new_links, source=source,
                               resume=resume, append=True)
            else:
                update_archive(out_dir, all_links, source=source,
                               resume=resume, append=True)

            # Step 4: Re-write links index with
            # updated titles, icons, and resources
            all_links, _ = load_links(archive_path=out_dir)
            write_links_index(out_dir=out_dir, links=all_links)

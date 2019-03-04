
from threading import Thread
from time import sleep


class ArchiveQueue(object):
    """Provide a queueing system between web interface and archiving agent."""

    """List of queued links to be processed."""
    QUEUE = []

    @classmethod
    def add_link_to_queue(cls, link):
        """Add link to be queued to proccessed."""
        ArchiveQueue.QUEUE.append(link)


class ArchiveAgent(Thread):
    """Threaded agent to perform archving."""

    # Class variable to store singleton instance.
    INSTANCE = None

    # Cached reference to 'old links'
    OLD_LINKS = None

    @classmethod
    def get_instance(cls):
        """Return singleton instance of thread"""
        if cls.INSTANCE is None:
            cls.INSTANCE = cls()

        return cls.INSTANCE

    def __init__(self):
        """Store member variable for starting/stopping"""
        self.stop = False

    def run(self):
        """Method for thread loop"""
        # Continue looping until stopped
        while not self.stop:

            # Iterate through list of links in queue.
            # Use copy, to ensure that altering the queue
            # whilst iterating does not cause any unwanted
            # side effects
            for link in list(ArchiveQueue.QUEUE):

                # Remove link from queue
                ArchiveQueue.QUEUE.remove(link)

            # Once complete, sleep for 5 seconds.
            sleep(5)


from flask import Flask

from archive_queue import ArchiveQueue, ArchiveAgent


class ApiServer(object):
    """Api server"""

    def __init__(self):
        """Create server object"""
        self.app = Flask('ArchiveBox')

        @self.app.route('/add-link/<string:url>')
        def add_link(url):
            """Add link to queue"""
            ArchiveQueue.add_link_to_queue(url)
            return url

    def start(self):
        """Start app"""
        self.app.run()


if __name__ == '__main__':
    # Create archive agent object and start
    # daemon
    ARCHIVE_AGENT = ArchiveAgent.get_instance()
    ARCHIVE_AGENT.start()

    # Create API server object and start
    API_SERVER = ApiServer()
    API_SERVER.start()

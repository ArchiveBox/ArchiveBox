# ArchiveBox
# MatthewJohn 2019 | MIT License
# https://github.com/matthewjohn/ArchiveBox


from flask import Flask, request

from archive_queue import ArchiveQueue, ArchiveAgent


class ApiServer(object):
    """Api server"""

    def __init__(self):
        """Create server object"""
        self.app = Flask('ArchiveBox')

        @self.app.route('/add-link')
        def add_link():
            """Add link to queue"""
            url = request.args.get('url')
            if url:
                ArchiveQueue.add_link_to_queue(url)
            return url or 'No link provided'

    def start(self):
        """Start app"""
        self.app.run(host='0.0.0.0')


if __name__ == '__main__':

    # Create archive agent object and start
    # daemon
    ARCHIVE_AGENT = ArchiveAgent.get_instance()
    ARCHIVE_AGENT.start()

    # Create API server object and start
    API_SERVER = ApiServer()
    API_SERVER.start()

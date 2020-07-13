from multiprocessing import Process

import pytest
from .mock_server.server import start

server_process = None

@pytest.hookimpl
def pytest_sessionstart(session):
    global server_process
    server_process = Process(target=start)
    server_process.start()

@pytest.hookimpl
def pytest_sessionfinish(session):
    if server_process is not None:
        server_process.terminate()
        server_process.join()
    
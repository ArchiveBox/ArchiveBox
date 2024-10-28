import abx


@abx.hookimpl
def get_CONFIG():
    from .config import CURL_CONFIG
    
    return {
        'curl': CURL_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import CURL_BINARY
    
    return {
        'curl': CURL_BINARY,
    }

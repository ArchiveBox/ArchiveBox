__package__ = 'abx_plugin_chrome'
__label__ = 'Chrome'
__author__ = 'ArchiveBox'

import abx

@abx.hookimpl
def get_CONFIG():
    from .config import CHROME_CONFIG
    
    return {
        'CHROME_CONFIG': CHROME_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import CHROME_BINARY
    
    return {
        'chrome': CHROME_BINARY,
    }

@abx.hookimpl
def ready():
    from .config import CHROME_CONFIG
    CHROME_CONFIG.validate()


@abx.hookimpl
def get_EXTRACTORS():
    """extractors that can be run for each URL, producing one or more ArchiveResults each"""
    from .extractors import PDF_EXTRACTOR, SCREENSHOT_EXTRACTOR, DOM_EXTRACTOR
    # dom           -> ./output.html      -> ./chrome_dom/index.html
    # screenshot    -> ./screenshot.png   -> ./chrome_screenshot/screenshot.png
    # pdf           -> ./output.pdf       -> ./chrome_pdf/pdf.pdf
    return {
        'pdf': PDF_EXTRACTOR,
        'screenshot': SCREENSHOT_EXTRACTOR,
        'dom': DOM_EXTRACTOR,
    }

__package__ = 'abx_plugin_chrome'

from abx_pkg import BinName

from abx_spec_extractor import BaseExtractor, ExtractorName

from .binaries import CHROME_BINARY


class PDFExtractor(BaseExtractor):
    name: ExtractorName = 'pdf'
    binary: BinName = CHROME_BINARY.name

PDF_EXTRACTOR = PDFExtractor()


class ScreenshotExtractor(BaseExtractor):
    name: ExtractorName = 'screenshot'
    binary: BinName = CHROME_BINARY.name

SCREENSHOT_EXTRACTOR = ScreenshotExtractor()

class DOMExtractor(BaseExtractor):
    name: ExtractorName = 'dom'
    binary: BinName = CHROME_BINARY.name
DOM_EXTRACTOR = DOMExtractor()

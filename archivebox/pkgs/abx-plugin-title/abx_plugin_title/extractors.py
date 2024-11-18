__package__ = 'abx_plugin_title'

from abx_spec_extractor import BaseExtractor, ExtractorName



class TitleExtractor(BaseExtractor):
    name: ExtractorName = 'title'

TITLE_EXTRACTOR = TitleExtractor()

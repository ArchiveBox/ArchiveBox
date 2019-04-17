__package__ = 'archivebox.legacy.storage'

from typing import List, Iterator

from ..schema import Link
from ..util import enforce_types
from ..config import setup_django


### Main Links Index

@enforce_types
def parse_sql_main_index() -> Iterator[Link]:
    setup_django()
    from core.models import Page

    return (
        page.as_json(*Page.keys)
        for page in Page.objects.all()
    )

@enforce_types
def write_sql_main_index(links: List[Link]) -> None:
    setup_django()
    from core.models import Page

    for link in links:
        info = {k: v for k, v in link._asdict().items() if k in Page.keys}
        Page.objects.update_or_create(url=link.url, defaults=info)

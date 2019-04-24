__package__ = 'archivebox.legacy.storage'

from typing import List, Iterator

from ..schema import Link
from ..util import enforce_types
from ..config import setup_django, OUTPUT_DIR


### Main Links Index

@enforce_types
def parse_sql_main_index(out_dir: str=OUTPUT_DIR) -> Iterator[Link]:
    setup_django(out_dir, check_db=True)
    from core.models import Page

    return (
        Link.from_json(page.as_json(*Page.keys))
        for page in Page.objects.all()
    )

@enforce_types
def write_sql_main_index(links: List[Link], out_dir: str=OUTPUT_DIR) -> None:
    setup_django(out_dir, check_db=True)
    from core.models import Page

    for link in links:
        info = {k: v for k, v in link._asdict().items() if k in Page.keys}
        Page.objects.update_or_create(url=link.url, defaults=info)

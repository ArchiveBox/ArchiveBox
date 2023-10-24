from django.db.models import QuerySet

from archivebox.util import enforce_types
from archivebox.config import ANSI

def log_index_started(url):
    print('{green}[*] Indexing url: {} in the search index {reset}'.format(url, **ANSI))
    print( )

def get_file_result_content(res, extra_path, use_pwd=False):
    if use_pwd: 
        fpath = f'{res.pwd}/{res.output}'
    else:
        fpath = f'{res.output}'
    
    if extra_path:
        fpath = f'{fpath}/{extra_path}'

    with open(fpath, 'r', encoding='utf-8') as file:
        data = file.read()
    if data:
        return [data]
    return []


# This should be abstracted by a plugin interface for extractors
@enforce_types
def get_indexable_content(results: QuerySet):
    if not results:
        return []
    # Only use the first method available
    res, method = results.first(), results.first().extractor
    if method not in ('readability', 'singlefile', 'dom', 'wget'):
        return []
    # This should come from a plugin interface

    # TODO: banish this duplication and get these from the extractor file
    if method == 'readability':
        return get_file_result_content(res, 'content.txt', use_pwd=True)
    elif method == 'singlefile':
        return get_file_result_content(res, '', use_pwd=True)
    elif method == 'dom':
        return get_file_result_content(res, '', use_pwd=True)
    elif method == 'wget':
        return get_file_result_content(res, '', use_pwd=True)

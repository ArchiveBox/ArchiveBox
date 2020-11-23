from django.db.models import QuerySet

from archivebox.util import enforce_types

def get_file_result_content(res, extra_path, use_pwd=False):
    if use_pwd: 
        fpath = f'{res.pwd}/{res.output}'
    else:
        fpath = f'{res.output}'
    
    if extra_path:
        fpath = f'{fpath}/{extra_path}'

    with open(fpath, 'r') as file:
        data = file.read().replace('\n', '')
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
    if method == 'readability':
        return get_file_result_content(res, 'content.txt')
    elif method == 'singlefile':
        return get_file_result_content(res, '')
    elif method == 'dom':
        return get_file_result_content(res,'',use_pwd=True)
    elif method == 'wget':
        return get_file_result_content(res,'',use_pwd=True)

__package__ = 'archivebox.api'


from io import StringIO
from traceback import format_exception
from contextlib import redirect_stdout, redirect_stderr

from django.http import HttpRequest, HttpResponse
from django.core.exceptions import ObjectDoesNotExist, EmptyResultSet, PermissionDenied

from ninja import NinjaAPI, Swagger

# TODO: explore adding https://eadwincode.github.io/django-ninja-extra/

from api.auth import API_AUTH_METHODS
from ..config import VERSION, COMMIT_HASH


COMMIT_HASH = COMMIT_HASH or 'unknown'

html_description=f'''
<h3>Welcome to your ArchiveBox server's REST API <code>[v1 ALPHA]</code> homepage!</h3>
<br/>
<i><b>WARNING: This API is still in an early development stage and may change!</b></i>
<br/>
<ul>
<li>⬅️ Manage your server: <a href="/admin/api/"><b>Setup API Keys</b></a>, <a href="/admin/">Go to your Server Admin UI</a>, <a href="/">Go to your Snapshots list</a> 
<li>💬 Ask questions and get help here: <a href="https://zulip.archivebox.io">ArchiveBox Chat Forum</a></li>
<li>🐞 Report API bugs here: <a href="https://github.com/ArchiveBox/ArchiveBox/issues">Github Issues</a></li>
<li>📚 ArchiveBox Documentation: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki">Github Wiki</a></li>
<li>📜 See the API source code: <a href="https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/api"><code>archivebox/api/</code></a></li>
</ul>
<small>Served by ArchiveBox v{VERSION} (<a href="https://github.com/ArchiveBox/ArchiveBox/commit/{COMMIT_HASH}"><code>{COMMIT_HASH[:8]}</code></a>), API powered by <a href="https://django-ninja.dev/"><code>django-ninja</code></a>.</small>
'''


def register_urls(api: NinjaAPI) -> NinjaAPI:
    api.add_router('/auth/',     'api.v1_auth.router')
    api.add_router('/core/',     'api.v1_core.router')
    api.add_router('/cli/',      'api.v1_cli.router')
    return api


class NinjaAPIWithIOCapture(NinjaAPI):    
    def create_temporal_response(self, request: HttpRequest) -> HttpResponse:
        stdout, stderr = StringIO(), StringIO()

        with redirect_stderr(stderr):
            with redirect_stdout(stdout):
                request.stdout = stdout
                request.stderr = stderr

                response = super().create_temporal_response(request)

        print('RESPONDING NOW', response)

        return response


api = NinjaAPIWithIOCapture(
    title='ArchiveBox API',
    description=html_description,
    version='1.0.0',
    csrf=False,
    auth=API_AUTH_METHODS,
    urls_namespace="api",
    docs=Swagger(settings={"persistAuthorization": True}),
    # docs_decorator=login_required,
    # renderer=ORJSONRenderer(),
)
api = register_urls(api)
urls = api.urls


@api.exception_handler(Exception)
def generic_exception_handler(request, err):
    status = 503
    if isinstance(err, (ObjectDoesNotExist, EmptyResultSet, PermissionDenied)):
        status = 404

    print(''.join(format_exception(err)))

    return api.create_response(
        request,
        {
            "succeeded": False,
            "message": f'{err.__class__.__name__}: {err}',
            "errors": [
                ''.join(format_exception(err)),
                # or send simpler parent-only traceback:
                # *([str(err.__context__)] if getattr(err, '__context__', None) else []),
            ],
        },
        status=status,
    )



# import orjson
# from ninja.renderers import BaseRenderer
# class ORJSONRenderer(BaseRenderer):
#     media_type = "application/json"
#     def render(self, request, data, *, response_status):
#         return {
#             "success": True,
#             "errors": [],
#             "result": data,
#             "stdout": ansi_to_html(stdout.getvalue().strip()),
#             "stderr": ansi_to_html(stderr.getvalue().strip()),
#         }
#         return orjson.dumps(data)

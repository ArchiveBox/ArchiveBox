__package__ = 'archivebox.core'

from typing import Callable

from io import StringIO
from contextlib import redirect_stdout

from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, Http404
from django.utils.html import format_html, mark_safe
from django.views import View, static
from django.views.generic.list import ListView
from django.views.generic import FormView
from django.db.models import Q
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from admin_data_views.typing import TableContext, ItemContext
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink


from core.models import Snapshot
from core.forms import AddLinkForm

from ..config import (
    OUTPUT_DIR,
    PUBLIC_INDEX,
    PUBLIC_SNAPSHOTS,
    PUBLIC_ADD_VIEW,
    VERSION,
    COMMIT_HASH,
    FOOTER_INFO,
    SNAPSHOTS_PER_PAGE,
    CONFIG,
    CONFIG_SCHEMA,
    DYNAMIC_CONFIG_SCHEMA,
    USER_CONFIG,
)
from ..main import add
from ..util import base_url, ansi_to_html
from ..search import query_search_index


class HomepageView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/admin/core/snapshot/')

        if PUBLIC_INDEX:
            return redirect('/public')

        return redirect(f'/admin/login/?next={request.path}')


class SnapshotView(View):
    # render static html index from filesystem archive/<timestamp>/index.html

    def get(self, request, path):
        if not request.user.is_authenticated and not PUBLIC_SNAPSHOTS:
            return redirect(f'/admin/login/?next={request.path}')

        try:
            slug, archivefile = path.split('/', 1)
        except (IndexError, ValueError):
            slug, archivefile = path.split('/', 1)[0], 'index.html'

        # slug is a timestamp
        if slug.replace('.','').isdigit():

            # missing trailing slash -> redirect to index
            if '/' not in path:
                return redirect(f'{path}/index.html')

            try:
                try:
                    snapshot = Snapshot.objects.get(Q(timestamp=slug) | Q(id__startswith=slug))
                    response = static.serve(request, archivefile, document_root=snapshot.link_dir, show_indexes=True)
                    response["Link"] = f'<{snapshot.url}>; rel="canonical"'
                    return response
                except Snapshot.DoesNotExist:
                    if Snapshot.objects.filter(timestamp__startswith=slug).exists():
                        raise Snapshot.MultipleObjectsReturned
                    else:
                        raise
            except Snapshot.DoesNotExist:
                # Snapshot does not exist
                return HttpResponse(
                    format_html(
                        (
                            '<center><br/><br/><br/>'
                            'No Snapshot directories match the given timestamp or UUID: <code>{}</code><br/><br/>'
                            'You can <a href="/add/" target="_top">add a new Snapshot</a>, or return to the <a href="/" target="_top">Main Index</a>'
                            '</center>'
                        ),
                        slug,
                        path,
                    ),
                    content_type="text/html",
                    status=404,
                )
            except Snapshot.MultipleObjectsReturned:
                snapshot_hrefs = mark_safe('<br/>').join(
                    format_html(
                        '{} <a href="/archive/{}/index.html"><b><code>{}</code></b></a> {} <b>{}</b>',
                        snap.added.strftime('%Y-%m-%d %H:%M:%S'),
                        snap.timestamp,
                        snap.timestamp,
                        snap.url,
                        snap.title or '',
                    )
                    for snap in Snapshot.objects.filter(timestamp__startswith=slug).only('url', 'timestamp', 'title', 'added').order_by('-added')
                )
                return HttpResponse(
                    format_html(
                        (
                            'Multiple Snapshots match the given timestamp/UUID <code>{}</code><br/><pre>'
                        ),
                        slug,
                    ) + snapshot_hrefs + format_html(
                        (
                            '</pre><br/>'
                            'Choose a Snapshot to proceed or go back to the <a href="/" target="_top">Main Index</a>'
                        )
                    ),
                    content_type="text/html",
                    status=404,
                )
            except Http404:
                # Snapshot dir exists but file within does not e.g. 124235.324234/screenshot.png
                return HttpResponse(
                    format_html(
                        (
                            '<center><br/><br/><br/>'
                            f'Snapshot <a href="/archive/{snapshot.timestamp}/index.html" target="_top"><b><code>[{snapshot.timestamp}]</code></b></a> exists in DB, but resource <b><code>{snapshot.timestamp}/'
                            '{}'
                            f'</code></b> does not exist in <a href="/archive/{snapshot.timestamp}/" target="_top">snapshot dir</a> yet.<br/><br/>'
                            'Maybe this resource type is not availabe for this Snapshot,<br/>or the archiving process has not completed yet?<br/>'
                            f'<pre><code># run this cmd to finish archiving this Snapshot<br/>archivebox update -t timestamp {snapshot.timestamp}</code></pre><br/><br/>'
                            '<div class="text-align: left; width: 100%; max-width: 400px">'
                            '<i><b>Next steps:</i></b><br/>'
                            f'- list all the <a href="/archive/{snapshot.timestamp}/" target="_top">Snapshot files <code>.*</code></a><br/>'
                            f'- view the <a href="/archive/{snapshot.timestamp}/index.html" target="_top">Snapshot <code>./index.html</code></a><br/>'
                            f'- go to the <a href="/admin/core/snapshot/{snapshot.id}/change/" target="_top">Snapshot admin</a> to edit<br/>'
                            f'- go to the <a href="/admin/core/snapshot/?id__startswith={snapshot.id}" target="_top">Snapshot actions</a> to re-archive<br/>'
                            '- or return to <a href="/" target="_top">the main index...</a></div>'
                            '</center>'
                        ),
                        archivefile,
                    ),
                    content_type="text/html",
                    status=404,
                )
        # slug is a URL
        try:
            try:
                # try exact match on full url first
                snapshot = Snapshot.objects.get(
                    Q(url='http://' + path) | Q(url='https://' + path) | Q(id__startswith=path)
                )
            except Snapshot.DoesNotExist:
                # fall back to match on exact base_url
                try:
                    snapshot = Snapshot.objects.get(
                        Q(url='http://' + base_url(path)) | Q(url='https://' + base_url(path))
                    )
                except Snapshot.DoesNotExist:
                    # fall back to matching base_url as prefix
                    snapshot = Snapshot.objects.get(
                        Q(url__startswith='http://' + base_url(path)) | Q(url__startswith='https://' + base_url(path))
                    )
            return redirect(f'/archive/{snapshot.timestamp}/index.html')
        except Snapshot.DoesNotExist:
            return HttpResponse(
                format_html(
                    (
                        '<center><br/><br/><br/>'
                        'No Snapshots match the given url: <code>{}</code><br/><br/><br/>'
                        'Return to the <a href="/" target="_top">Main Index</a>, or:<br/><br/>'
                        '+ <i><a href="/add/?url={}" target="_top">Add a new Snapshot for <code>{}</code></a><br/><br/></i>'
                        '</center>'
                    ),
                    base_url(path),
                    path if '://' in path else f'https://{path}',
                    path,
                ),
                content_type="text/html",
                status=404,
            )
        except Snapshot.MultipleObjectsReturned:
            snapshot_hrefs = mark_safe('<br/>').join(
                format_html(
                    '{} <a href="/archive/{}/index.html"><b><code>{}</code></b></a> {} <b>{}</b>',
                    snap.added.strftime('%Y-%m-%d %H:%M:%S'),
                    snap.timestamp,
                    snap.timestamp,
                    snap.url,
                    snap.title or '',
                )
                for snap in Snapshot.objects.filter(
                    Q(url__startswith='http://' + base_url(path)) | Q(url__startswith='https://' + base_url(path))
                ).only('url', 'timestamp', 'title', 'added').order_by('-added')
            )
            return HttpResponse(
                format_html(
                    (
                        'Multiple Snapshots match the given URL <code>{}</code><br/><pre>'
                    ),
                    base_url(path),
                ) + snapshot_hrefs + format_html(
                    (
                        '</pre><br/>'
                        'Choose a Snapshot to proceed or go back to the <a href="/" target="_top">Main Index</a>'
                    )
                ),
                content_type="text/html",
                status=404,
            )


class PublicIndexView(ListView):
    template_name = 'public_index.html'
    model = Snapshot
    paginate_by = SNAPSHOTS_PER_PAGE
    ordering = ['-added']

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'VERSION': VERSION,
            'COMMIT_HASH': COMMIT_HASH,
            'FOOTER_INFO': FOOTER_INFO,
        }

    def get_queryset(self, **kwargs):
        qs = super().get_queryset(**kwargs)
        query = self.request.GET.get('q')
        if query and query.strip():
            qs = qs.filter(Q(title__icontains=query) | Q(url__icontains=query) | Q(timestamp__icontains=query) | Q(tags__name__icontains=query))
            try:
                qs = qs | query_search_index(query)
            except Exception as err:
                print(f'[!] Error while using search backend: {err.__class__.__name__} {err}')
        return qs.distinct()

    def get(self, *args, **kwargs):
        if PUBLIC_INDEX or self.request.user.is_authenticated:
            response = super().get(*args, **kwargs)
            return response
        else:
            return redirect(f'/admin/login/?next={self.request.path}')

@method_decorator(csrf_exempt, name='dispatch')
class AddView(UserPassesTestMixin, FormView):
    template_name = "add.html"
    form_class = AddLinkForm

    def get_initial(self):
        """Prefill the AddLinkForm with the 'url' GET parameter"""
        if self.request.method == 'GET':
            url = self.request.GET.get('url', None)
            if url:
                return {'url': url if '://' in url else f'https://{url}'}

        return super().get_initial()

    def test_func(self):
        return PUBLIC_ADD_VIEW or self.request.user.is_authenticated

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'title': "Add URLs",
            # We can't just call request.build_absolute_uri in the template, because it would include query parameters
            'absolute_add_path': self.request.build_absolute_uri(self.request.path),
            'VERSION': VERSION,
            'FOOTER_INFO': FOOTER_INFO,
            'stdout': '',
        }

    def form_valid(self, form):
        url = form.cleaned_data["url"]
        print(f'[+] Adding URL: {url}')
        parser = form.cleaned_data["parser"]
        tag = form.cleaned_data["tag"]
        depth = 0 if form.cleaned_data["depth"] == "0" else 1
        extractors = ','.join(form.cleaned_data["archive_methods"])
        input_kwargs = {
            "urls": url,
            "tag": tag,
            "depth": depth,
            "parser": parser,
            "update_all": False,
            "out_dir": OUTPUT_DIR,
        }
        if extractors:
            input_kwargs.update({"extractors": extractors})
        add_stdout = StringIO()
        with redirect_stdout(add_stdout):
            add(**input_kwargs)
            print(add_stdout.getvalue())

        context = self.get_context_data()

        context.update({
            "stdout": ansi_to_html(add_stdout.getvalue().strip()),
            "form": AddLinkForm()
        })
        return render(template_name=self.template_name, request=self.request, context=context)


class HealthCheckView(View):
    """
    A Django view that renders plain text "OK" for service discovery tools
    """
    def get(self, request):
        """
        Handle a GET request
        """
        return HttpResponse(
            'OK',
            content_type='text/plain',
            status=200
        )


def find_config_section(key: str) -> str:
    matching_sections = [
        name for name, opts in CONFIG_SCHEMA.items() if key in opts
    ]
    section = matching_sections[0] if matching_sections else 'DYNAMIC'
    return section

def find_config_default(key: str) -> str:
    default_val = USER_CONFIG.get(key, {}).get('default', lambda: None)
    if isinstance(default_val, Callable):
        return None
    else:
        default_val = repr(default_val)
    return default_val

def find_config_type(key: str) -> str:
    if key in USER_CONFIG:
        return USER_CONFIG[key]['type'].__name__
    elif key in DYNAMIC_CONFIG_SCHEMA:
        return type(CONFIG[key]).__name__
    return 'str'

def key_is_safe(key: str) -> bool:
    for term in ('key', 'password', 'secret', 'token'):
        if term in key.lower():
            return False
    return True

@render_with_table_view
def live_config_list_view(request: HttpRequest, **kwargs) -> TableContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    rows = {
        "Section": [],
        "Key": [],
        "Type": [],
        "Value": [],
        "Default": [],
        # "Documentation": [],
        "Aliases": [],
    }

    for section in CONFIG_SCHEMA.keys():
        for key in CONFIG_SCHEMA[section].keys():
            rows['Section'].append(section.replace('_', ' ').title().replace(' Config', ''))
            rows['Key'].append(ItemLink(key, key=key))
            rows['Type'].append(mark_safe(f'<code>{find_config_type(key)}</code>'))
            rows['Value'].append(mark_safe(f'<code>{CONFIG[key]}</code>') if key_is_safe(key) else '******** (redacted)')
            rows['Default'].append(mark_safe(f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig.py+%27{key}%27&type=code"><code style="text-decoration: underline">{find_config_default(key) or 'See here...'}</code></a>'))
            # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
            rows['Aliases'].append(', '.join(CONFIG_SCHEMA[section][key].get('aliases', [])))

    section = 'DYNAMIC'
    for key in DYNAMIC_CONFIG_SCHEMA.keys():
        rows['Section'].append(section.replace('_', ' ').title().replace(' Config', ''))
        rows['Key'].append(ItemLink(key, key=key))
        rows['Type'].append(mark_safe(f'<code>{find_config_type(key)}</code>'))
        rows['Value'].append(mark_safe(f'<code>{CONFIG[key]}</code>') if key_is_safe(key) else '******** (redacted)')
        rows['Default'].append(mark_safe(f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig.py+%27{key}%27&type=code"><code style="text-decoration: underline">{find_config_default(key) or 'See here...'}</code></a>'))
        # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
        rows['Aliases'].append(ItemLink(key, key=key) if key in USER_CONFIG else '')

    return TableContext(
        title="Computed Configuration Values",
        table=rows,
    )

@render_with_item_view
def live_config_value_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    aliases = USER_CONFIG.get(key, {}).get("aliases", [])

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": mark_safe(f'data / ArchiveBox.conf &nbsp; [{find_config_section(key)}]  &nbsp; <b><code style="color: lightgray">{key}</code></b>' if key in USER_CONFIG else f'[DYNAMIC CONFIG]   &nbsp; <b><code style="color: lightgray">{key}</code></b> &nbsp; <small>(calculated at runtime)</small>'),
                "description": None,
                "fields": {
                    'Key': key,
                    'Type': find_config_type(key),
                    'Value': CONFIG[key] if key_is_safe(key) else '********',
                },
                "help_texts": {
                    'Key': mark_safe(f'''
                        <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">Documentation</a>  &nbsp;
                        <span style="display: {"inline" if aliases else "none"}">
                            Aliases: {", ".join(aliases)}
                        </span>
                    '''),
                    'Type': mark_safe(f'''
                        <a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig.py+%27{key}%27&type=code">
                            See full definition in <code>archivebox/config.py</code>...
                        </a>
                    '''),
                    'Value': mark_safe(f'''
                        {'<b style="color: red">Value is redacted for your security. (Passwords, secrets, API tokens, etc. cannot be viewed in the Web UI)</b><br/><br/>' if not key_is_safe(key) else ''}
                        Default: <a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig.py+%27{key}%27&type=code">
                            <code>{find_config_default(key) or 'See 1here...'}</code>
                        </a>
                        <br/><br/>
                        <p style="display: {"block" if key in USER_CONFIG else "none"}">
                            <i>To change this value, edit <code>data/ArchiveBox.conf</code> or run:</i>
                            <br/><br/>
                            <code>archivebox config --set {key}="{
                                val.strip("'")
                                if (val := find_config_default(key)) else
                                (repr(CONFIG[key] if key_is_safe(key) else '********')).strip("'")
                            }"</code>
                        </p>
                    '''),
                },
            },
        ],
    )

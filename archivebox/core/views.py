__package__ = 'archivebox.core'

import os
import sys
from django.utils import timezone
import inspect
from typing import Callable, get_type_hints
from pathlib import Path

from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, Http404
from django.utils.html import format_html, mark_safe
from django.views import View
from django.views.generic.list import ListView
from django.views.generic import FormView
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from admin_data_views.typing import TableContext, ItemContext
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

import archivebox
from archivebox.config import CONSTANTS, CONSTANTS_CONFIG, DATA_DIR, VERSION
from archivebox.config.common import SHELL_CONFIG, SERVER_CONFIG
from archivebox.misc.util import base_url, htmlencode, ts_to_date_str
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.misc.logging_util import printable_filesize
from archivebox.search import query_search_index

from core.models import Snapshot
from core.forms import AddLinkForm
from crawls.models import Seed, Crawl



class HomepageView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/admin/core/snapshot/')

        if SERVER_CONFIG.PUBLIC_INDEX:
            return redirect('/public')

        return redirect(f'/admin/login/?next={request.path}')


class SnapshotView(View):
    # render static html index from filesystem archive/<timestamp>/index.html

    @staticmethod
    def render_live_index(request, snapshot):
        TITLE_LOADING_MSG = 'Not yet archived...'
        HIDDEN_RESULTS = ('favicon', 'headers', 'title', 'htmltotext', 'warc', 'archive_org')

        archiveresults = {}

        results = snapshot.archiveresult_set.all()

        for result in results:
            embed_path = result.embed_path()
            abs_path = result.snapshot_dir / (embed_path or 'None')

            if (result.status == 'succeeded'
                and (result.extractor not in HIDDEN_RESULTS)
                and embed_path
                and os.access(abs_path, os.R_OK)
                and abs_path.exists()):
                if os.path.isdir(abs_path) and not any(abs_path.glob('*.*')):
                    continue

                result_info = {
                    'name': result.extractor,
                    'path': embed_path,
                    'ts': ts_to_date_str(result.end_ts),
                    'size': abs_path.stat().st_size or '?',
                }
                archiveresults[result.extractor] = result_info

        existing_files = {result['path'] for result in archiveresults.values()}
        min_size_threshold = 10_000  # bytes
        allowed_extensions = {
            'txt',
            'html',
            'htm',
            'png',
            'jpg',
            'jpeg',
            'gif',
            'webp'
            'svg',
            'webm',
            'mp4',
            'mp3',
            'opus',
            'pdf',
            'md',
        }


        # iterate through all the files in the snapshot dir and add the biggest ones to1 the result list
        snap_dir = Path(snapshot.link_dir)
        if not os.path.isdir(snap_dir) and os.access(snap_dir, os.R_OK):
            return {}
        
        for result_file in (*snap_dir.glob('*'), *snap_dir.glob('*/*')):
            extension = result_file.suffix.lstrip('.').lower()
            if result_file.is_dir() or result_file.name.startswith('.') or extension not in allowed_extensions:
                continue
            if result_file.name in existing_files or result_file.name == 'index.html':
                continue

            file_size = result_file.stat().st_size or 0

            if file_size > min_size_threshold:
                archiveresults[result_file.name] = {
                    'name': result_file.stem,
                    'path': result_file.relative_to(snap_dir),
                    'ts': ts_to_date_str(result_file.stat().st_mtime or 0),
                    'size': file_size,
                }

        preferred_types = ('singlefile', 'screenshot', 'wget', 'dom', 'media', 'pdf', 'readability', 'mercury')
        all_types = preferred_types + tuple(result_type for result_type in archiveresults.keys() if result_type not in preferred_types)

        best_result = {'path': 'None'}
        for result_type in preferred_types:
            if result_type in archiveresults:
                best_result = archiveresults[result_type]
                break

        link = snapshot.as_link()

        link_info = link._asdict(extended=True)

        try:
            warc_path = 'warc/' + list(Path(snap_dir).glob('warc/*.warc.*'))[0].name
        except IndexError:
            warc_path = 'warc/'

        context = {
            **link_info,
            **link_info['canonical'],
            'title': htmlencode(
                link.title
                or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
            ),
            'extension': link.extension or 'html',
            'tags': link.tags or 'untagged',
            'size': printable_filesize(link.archive_size) if link.archive_size else 'pending',
            'status': 'archived' if link.is_archived else 'not yet archived',
            'status_color': 'success' if link.is_archived else 'danger',
            'oldest_archive_date': ts_to_date_str(link.oldest_archive_date),
            'warc_path': warc_path,
            'SAVE_ARCHIVE_DOT_ORG': archivebox.pm.hook.get_FLAT_CONFIG().SAVE_ARCHIVE_DOT_ORG,
            'PREVIEW_ORIGINALS': SERVER_CONFIG.PREVIEW_ORIGINALS,
            'archiveresults': sorted(archiveresults.values(), key=lambda r: all_types.index(r['name']) if r['name'] in all_types else -r['size']),
            'best_result': best_result,
            # 'tags_str': 'somealskejrewlkrjwer,werlmwrwlekrjewlkrjwer324m532l,4m32,23m324234',
        }
        return render(template_name='core/snapshot_live.html', request=request, context=context)


    def get(self, request, path):
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return redirect(f'/admin/login/?next={request.path}')

        snapshot = None

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
                    if archivefile == 'index.html':
                        # if they requested snapshot index, serve live rendered template instead of static html
                        response = self.render_live_index(request, snapshot)
                    else:
                        response = serve_static_with_byterange_support(
                            request, archivefile, document_root=snapshot.link_dir, show_indexes=True,
                        )
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
                            'No Snapshot directories match the given timestamp/ID/ABID: <code>{}</code><br/><br/>'
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
                        snap.bookmarked_at.strftime('%Y-%m-%d %H:%M:%S'),
                        snap.timestamp,
                        snap.timestamp,
                        snap.url,
                        snap.title_stripped[:64] or '',
                    )
                    for snap in Snapshot.objects.filter(timestamp__startswith=slug).only('url', 'timestamp', 'title', 'bookmarked_at').order_by('-bookmarked_at')
                )
                return HttpResponse(
                    format_html(
                        (
                            'Multiple Snapshots match the given timestamp/ID/ABID <code>{}</code><br/><pre>'
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
                assert snapshot     # (Snapshot.DoesNotExist is already handled above)

                # Snapshot dir exists but file within does not e.g. 124235.324234/screenshot.png
                return HttpResponse(
                    format_html(
                        (
                            '<center><br/><br/><br/>'
                            f'Snapshot <a href="/archive/{snapshot.timestamp}/index.html" target="_top"><b><code>[{snapshot.timestamp}]</code></b></a>: <a href="{snapshot.url}" target="_blank" rel="noreferrer">{snapshot.url}</a><br/>'
                            f'was queued on {str(snapshot.bookmarked_at).split(".")[0]}, '
                            f'but no files have been saved yet in:<br/><b><a href="/archive/{snapshot.timestamp}/" target="_top"><code>{snapshot.timestamp}</code></a><code>/'
                            '{}'
                            f'</code></b><br/><br/>'
                            'It\'s possible {} '
                            f'during the last capture on {str(snapshot.bookmarked_at).split(".")[0]},<br/>or that the archiving process has not completed yet.<br/>'
                            f'<pre><code># run this cmd to finish/retry archiving this Snapshot</code><br/>'
                            f'<code style="user-select: all; color: #333">archivebox update -t timestamp {snapshot.timestamp}</code></pre><br/><br/>'
                            '<div class="text-align: left; width: 100%; max-width: 400px">'
                            '<i><b>Next steps:</i></b><br/>'
                            f'- list all the <a href="/archive/{snapshot.timestamp}/" target="_top">Snapshot files <code>.*</code></a><br/>'
                            f'- view the <a href="/archive/{snapshot.timestamp}/index.html" target="_top">Snapshot <code>./index.html</code></a><br/>'
                            f'- go to the <a href="/admin/core/snapshot/{snapshot.pk}/change/" target="_top">Snapshot admin</a> to edit<br/>'
                            f'- go to the <a href="/admin/core/snapshot/?id__exact={snapshot.id}" target="_top">Snapshot actions</a> to re-archive<br/>'
                            '- or return to <a href="/" target="_top">the main index...</a></div>'
                            '</center>'
                        ),
                        archivefile if str(archivefile) != 'None' else '',
                        f'the {archivefile} resource could not be fetched' if str(archivefile) != 'None' else 'the original site was not available',
                    ),
                    content_type="text/html",
                    status=404,
                )
            
        # # slud is an ID
        # ulid = slug.split('_', 1)[-1]
        # try:
        #     try:
        #         snapshot = snapshot or Snapshot.objects.get(Q(abid=ulid) | Q(id=ulid))
        #     except Snapshot.DoesNotExist:
        #         pass

        #     try:
        #         snapshot = Snapshot.objects.get(Q(abid__startswith=slug) | Q(abid__startswith=Snapshot.abid_prefix + slug) | Q(id__startswith=slug))
        #     except (Snapshot.DoesNotExist, Snapshot.MultipleObjectsReturned):
        #         pass

        #     try:
        #         snapshot = snapshot or Snapshot.objects.get(Q(abid__icontains=snapshot_id) | Q(id__icontains=snapshot_id))
        #     except Snapshot.DoesNotExist:
        #         pass
        #     return redirect(f'/archive/{snapshot.timestamp}/index.html')
        # except Snapshot.DoesNotExist:
        #     pass

        # slug is a URL
        try:
            try:
                # try exact match on full url / ABID first
                snapshot = Snapshot.objects.get(
                    Q(url='http://' + path) | Q(url='https://' + path) | Q(id__startswith=path)
                    | Q(abid__icontains=path) | Q(id__icontains=path)
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
                    '{} <code style="font-size: 0.8em">{}</code> <a href="/archive/{}/index.html"><b><code>{}</code></b></a> {} <b>{}</b>',
                    snap.bookmarked_at.strftime('%Y-%m-%d %H:%M:%S'),
                    snap.abid,
                    snap.timestamp,
                    snap.timestamp,
                    snap.url,
                    snap.title_stripped[:64] or '',
                )
                for snap in Snapshot.objects.filter(
                    Q(url__startswith='http://' + base_url(path)) | Q(url__startswith='https://' + base_url(path))
                    | Q(abid__icontains=path) | Q(id__icontains=path)
                ).only('url', 'timestamp', 'title', 'bookmarked_at').order_by('-bookmarked_at')
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
    paginate_by = SERVER_CONFIG.SNAPSHOTS_PER_PAGE
    ordering = ['-bookmarked_at', '-created_at']

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'VERSION': VERSION,
            'COMMIT_HASH': SHELL_CONFIG.COMMIT_HASH,
            'FOOTER_INFO': SERVER_CONFIG.FOOTER_INFO,
        }

    def get_queryset(self, **kwargs):
        qs = super().get_queryset(**kwargs)
        query = self.request.GET.get('q', default = '').strip()

        if not query:
            return qs.distinct()

        query_type = self.request.GET.get('query_type')

        if not query_type or query_type == 'all':
            qs = qs.filter(Q(title__icontains=query) | Q(url__icontains=query) | Q(timestamp__icontains=query) | Q(tags__name__icontains=query))
            try:
                qs = qs | query_search_index(query)
            except Exception as err:
                print(f'[!] Error while using search backend: {err.__class__.__name__} {err}')
        elif query_type == 'fulltext':
            try:
                qs = qs | query_search_index(query)
            except Exception as err:
                print(f'[!] Error while using search backend: {err.__class__.__name__} {err}')
        elif query_type == 'meta':
            qs = qs.filter(Q(title__icontains=query) | Q(url__icontains=query) | Q(timestamp__icontains=query) | Q(tags__name__icontains=query))
        elif query_type == 'url':
            qs = qs.filter(Q(url__icontains=query))
        elif query_type == 'title':
            qs = qs.filter(Q(title__icontains=query))
        elif query_type == 'timestamp':
            qs = qs.filter(Q(timestamp__icontains=query))
        elif query_type == 'tags':
            qs = qs.filter(Q(tags__name__icontains=query))
        else:
            print(f'[!] Unknown value for query_type: "{query_type}"')

        return qs.distinct()

    def get(self, *args, **kwargs):
        if SERVER_CONFIG.PUBLIC_INDEX or self.request.user.is_authenticated:
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
        return SERVER_CONFIG.PUBLIC_ADD_VIEW or self.request.user.is_authenticated

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'title': "Add URLs",
            # We can't just call request.build_absolute_uri in the template, because it would include query parameters
            'absolute_add_path': self.request.build_absolute_uri(self.request.path),
            'VERSION': VERSION,
            'FOOTER_INFO': SERVER_CONFIG.FOOTER_INFO,
            'stdout': '',
        }

    def form_valid(self, form):
        urls = form.cleaned_data["url"]
        print(f'[+] Adding URL: {urls}')
        parser = form.cleaned_data["parser"]
        tag = form.cleaned_data["tag"]
        depth = 0 if form.cleaned_data["depth"] == "0" else 1
        extractors = ','.join(form.cleaned_data["archive_methods"])
        input_kwargs = {
            "urls": urls,
            "tag": tag,
            "depth": depth,
            "parser": parser,
            "update_all": False,
            "out_dir": DATA_DIR,
            "created_by_id": self.request.user.pk,
        }
        if extractors:
            input_kwargs.update({"extractors": extractors})

        
        from archivebox.config.permissions import HOSTNAME
    
    
        # 1. save the provided urls to sources/2024-11-05__23-59-59__web_ui_add_by_user_<user_pk>.txt
        sources_file = CONSTANTS.SOURCES_DIR / f'{timezone.now().strftime("%Y-%m-%d__%H-%M-%S")}__web_ui_add_by_user_{self.request.user.pk}.txt'
        sources_file.write_text(urls if isinstance(urls, str) else '\n'.join(urls))
        
        # 2. create a new Seed pointing to the sources/2024-11-05__23-59-59__web_ui_add_by_user_<user_pk>.txt
        seed = Seed.from_file(
            sources_file,
            label=f'{self.request.user.username}@{HOSTNAME}{self.request.path}',
            parser=parser,
            tag=tag,
            created_by=self.request.user.pk,
            config={
                # 'ONLY_NEW': not update,
                # 'INDEX_ONLY': index_only,
                # 'OVERWRITE': False,
                'DEPTH': depth,
                'EXTRACTORS': parser,
                # 'DEFAULT_PERSONA': persona or 'Default',
            })
        # 3. create a new Crawl pointing to the Seed
        crawl = Crawl.from_seed(seed, max_depth=depth)
        
        # 4. start the Orchestrator & wait until it completes
        #    ... orchestrator will create the root Snapshot, which creates pending ArchiveResults, which gets run by the ArchiveResultActors ...
        # from crawls.actors import CrawlActor
        # from core.actors import SnapshotActor, ArchiveResultActor
    

        rough_url_count = urls.count('://')

        messages.success(
            self.request,
            mark_safe(f"Adding {rough_url_count} URLs in the background. (refresh in a minute start seeing results) {crawl.admin_change_url}"),
        )
        # if not bg:
        #     from workers.orchestrator import Orchestrator
        #     orchestrator = Orchestrator(exit_on_idle=True, max_concurrent_actors=4)
        #     orchestrator.start()

        return redirect(crawl.admin_change_url)


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
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    
    if key in CONSTANTS_CONFIG:
        return 'CONSTANT'
    matching_sections = [
        section_id for section_id, section in CONFIGS.items() if key in dict(section)
    ]
    section = matching_sections[0] if matching_sections else 'DYNAMIC'
    return section

def find_config_default(key: str) -> str:
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    
    if key in CONSTANTS_CONFIG:
        return str(CONSTANTS_CONFIG[key])
    
    default_val = None

    for config in CONFIGS.values():
        if key in dict(config):
            default_field = getattr(config, 'model_fields', dict(config))[key]
            default_val = default_field.default if hasattr(default_field, 'default') else default_field
            break
        
    if isinstance(default_val, Callable):
        default_val = inspect.getsource(default_val).split('lambda', 1)[-1].split(':', 1)[-1].replace('\n', ' ').strip()
        if default_val.count(')') > default_val.count('('):
            default_val = default_val[:-1]
    else:
        default_val = str(default_val)
        
    return default_val

def find_config_type(key: str) -> str:
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    
    for config in CONFIGS.values():
        if hasattr(config, key):
            type_hints = get_type_hints(config)
            try:
                return str(type_hints[key].__name__)
            except AttributeError:
                return str(type_hints[key])
    return 'str'

def key_is_safe(key: str) -> bool:
    for term in ('key', 'password', 'secret', 'token'):
        if term in key.lower():
            return False
    return True

@render_with_table_view
def live_config_list_view(request: HttpRequest, **kwargs) -> TableContext:
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    
    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    rows = {
        "Section": [],
        "Key": [],
        "Type": [],
        "Value": [],
        "Default": [],
        # "Documentation": [],
        # "Aliases": [],
    }

    for section_id, section in reversed(list(CONFIGS.items())):
        for key in dict(section).keys():
            rows['Section'].append(section_id)   # section.replace('_', ' ').title().replace(' Config', '')
            rows['Key'].append(ItemLink(key, key=key))
            rows['Type'].append(format_html('<code>{}</code>', find_config_type(key)))
            rows['Value'].append(mark_safe(f'<code>{getattr(section, key)}</code>') if key_is_safe(key) else '******** (redacted)')
            rows['Default'].append(mark_safe(f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code"><code style="text-decoration: underline">{find_config_default(key) or "See here..."}</code></a>'))
            # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
            # rows['Aliases'].append(', '.join(find_config_aliases(key)))

    section = 'CONSTANT'
    for key in CONSTANTS_CONFIG.keys():
        rows['Section'].append(section)   # section.replace('_', ' ').title().replace(' Config', '')
        rows['Key'].append(ItemLink(key, key=key))
        rows['Type'].append(format_html('<code>{}</code>', getattr(type(CONSTANTS_CONFIG[key]), '__name__', str(CONSTANTS_CONFIG[key]))))
        rows['Value'].append(format_html('<code>{}</code>', CONSTANTS_CONFIG[key]) if key_is_safe(key) else '******** (redacted)')
        rows['Default'].append(mark_safe(f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code"><code style="text-decoration: underline">{find_config_default(key) or "See here..."}</code></a>'))
        # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
        # rows['Aliases'].append('')


    return TableContext(
        title="Computed Configuration Values",
        table=rows,
    )

@render_with_item_view
def live_config_value_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    FLAT_CONFIG = archivebox.pm.hook.get_FLAT_CONFIG()
    
    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    # aliases = USER_CONFIG.get(key, {}).get("aliases", [])
    aliases = []

    if key in CONSTANTS_CONFIG:
        section_header = mark_safe(f'[CONSTANTS]   &nbsp; <b><code style="color: lightgray">{key}</code></b> &nbsp; <small>(read-only, hardcoded by ArchiveBox)</small>')
    elif key in FLAT_CONFIG:
        section_header = mark_safe(f'data / ArchiveBox.conf &nbsp; [{find_config_section(key)}]  &nbsp; <b><code style="color: lightgray">{key}</code></b>')
    else:
        section_header = mark_safe(f'[DYNAMIC CONFIG]   &nbsp; <b><code style="color: lightgray">{key}</code></b> &nbsp; <small>(read-only, calculated at runtime)</small>')


    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": section_header,
                "description": None,
                "fields": {
                    'Key': key,
                    'Type': find_config_type(key),
                    'Value': FLAT_CONFIG.get(key, CONFIGS.get(key, None)) if key_is_safe(key) else '********',
                },
                "help_texts": {
                    'Key': mark_safe(f'''
                        <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">Documentation</a>  &nbsp;
                        <span style="display: {"inline" if aliases else "none"}">
                            Aliases: {", ".join(aliases)}
                        </span>
                    '''),
                    'Type': mark_safe(f'''
                        <a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code">
                            See full definition in <code>archivebox/config</code>...
                        </a>
                    '''),
                    'Value': mark_safe(f'''
                        {'<b style="color: red">Value is redacted for your security. (Passwords, secrets, API tokens, etc. cannot be viewed in the Web UI)</b><br/><br/>' if not key_is_safe(key) else ''}
                        <br/><hr/><br/>
                        Default: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; 
                        <a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code">
                            <code>{find_config_default(key) or '↗️ See in ArchiveBox source code...'}</code>
                        </a>
                        <br/><br/>
                        <p style="display: {"block" if key in FLAT_CONFIG and key not in CONSTANTS_CONFIG else "none"}">
                            <i>To change this value, edit <code>data/ArchiveBox.conf</code> or run:</i>
                            <br/><br/>
                            <code>archivebox config --set {key}="{
                                val.strip("'")
                                if (val := find_config_default(key)) else
                                (str(FLAT_CONFIG[key] if key_is_safe(key) else '********')).strip("'")
                            }"</code>
                        </p>
                    '''),
                },
            },
        ],
    )

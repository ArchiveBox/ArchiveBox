__package__ = 'archivebox.core'

import os
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
from archivebox.config.common import SHELL_CONFIG, SERVER_CONFIG, ARCHIVING_CONFIG
from archivebox.config.configset import get_flat_config, get_config, get_all_configs
from archivebox.misc.util import base_url, htmlencode, ts_to_date_str, urldecode
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.misc.logging_util import printable_filesize
from archivebox.search import query_search_index

from archivebox.core.models import Snapshot
from archivebox.core.forms import AddLinkForm
from archivebox.crawls.models import Crawl
from archivebox.hooks import get_enabled_plugins, get_plugin_name



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
    def find_snapshots_for_url(path: str):
        """Return a queryset of snapshots matching a URL-ish path."""
        normalized = path
        if path.startswith(('http://', 'https://')):
            # try exact match on full url / ID first
            qs = Snapshot.objects.filter(Q(url=path) | Q(id__icontains=path))
            if qs.exists():
                return qs
            normalized = path.split('://', 1)[1]

        # try exact match on full url / ID (without scheme)
        qs = Snapshot.objects.filter(
            Q(url='http://' + normalized) | Q(url='https://' + normalized) | Q(id__icontains=normalized)
        )
        if qs.exists():
            return qs

        # fall back to match on exact base_url
        base = base_url(normalized)
        qs = Snapshot.objects.filter(
            Q(url='http://' + base) | Q(url='https://' + base)
        )
        if qs.exists():
            return qs

        # fall back to matching base_url as prefix
        return Snapshot.objects.filter(
            Q(url__startswith='http://' + base) | Q(url__startswith='https://' + base)
        )

    @staticmethod
    def render_live_index(request, snapshot):
        TITLE_LOADING_MSG = 'Not yet archived...'

        outputs = snapshot.discover_outputs()
        archiveresults = {out['name']: out for out in outputs}
        snap_dir = Path(snapshot.output_dir)

        # Get available extractor plugins from hooks (sorted by numeric prefix for ordering)
        # Convert to base names for display ordering
        all_plugins = [get_plugin_name(e) for e in get_enabled_plugins()]
        preview_priority = [
            'singlefile',
            'screenshot',
            'wget',
            'dom',
            'pdf',
            'readability',
        ]
        preferred_types = tuple(preview_priority + [p for p in all_plugins if p not in preview_priority])
        all_types = preferred_types + tuple(result_type for result_type in archiveresults.keys() if result_type not in preferred_types)

        best_result = {'path': 'about:blank', 'result': None}
        for result_type in preferred_types:
            if result_type in archiveresults:
                best_result = archiveresults[result_type]
                break

        snapshot_info = snapshot.to_dict(extended=True)

        try:
            warc_path = 'warc/' + list(Path(snap_dir).glob('warc/*.warc.*'))[0].name
        except IndexError:
            warc_path = 'warc/'

        context = {
            **snapshot_info,
            'title': htmlencode(
                snapshot.title
                or (snapshot.base_url if snapshot.is_archived else TITLE_LOADING_MSG)
            ),
            'extension': snapshot.extension or 'html',
            'tags': snapshot.tags_str() or 'untagged',
            'size': printable_filesize(snapshot.archive_size) if snapshot.archive_size else 'pending',
            'status': 'archived' if snapshot.is_archived else 'not yet archived',
            'status_color': 'success' if snapshot.is_archived else 'danger',
            'oldest_archive_date': ts_to_date_str(snapshot.oldest_archive_date),
            'warc_path': warc_path,
            'PREVIEW_ORIGINALS': SERVER_CONFIG.PREVIEW_ORIGINALS,
            'archiveresults': sorted(archiveresults.values(), key=lambda r: all_types.index(r['name']) if r['name'] in all_types else -r['size']),
            'best_result': best_result,
            'snapshot': snapshot,  # Pass the snapshot object for template tags
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
                    canonical_base = snapshot.url_path
                    if canonical_base != snapshot.legacy_archive_path:
                        target_path = f'/{canonical_base}/{archivefile or "index.html"}'
                        query = request.META.get('QUERY_STRING')
                        if query:
                            target_path = f'{target_path}?{query}'
                        return redirect(target_path)

                    if archivefile == 'index.html':
                        # if they requested snapshot index, serve live rendered template instead of static html
                        response = self.render_live_index(request, snapshot)
                    else:
                        response = serve_static_with_byterange_support(
                            request, archivefile, document_root=snapshot.output_dir, show_indexes=True,
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
                            'No Snapshot directories match the given timestamp/ID: <code>{}</code><br/><br/>'
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
                        '{} <a href="/{}/index.html"><b><code>{}</code></b></a> {} <b>{}</b>',
                        snap.bookmarked_at.strftime('%Y-%m-%d %H:%M:%S'),
                        snap.archive_path,
                        snap.timestamp,
                        snap.url,
                        snap.title_stripped[:64] or '',
                    )
                    for snap in Snapshot.objects.filter(timestamp__startswith=slug).only('url', 'timestamp', 'title', 'bookmarked_at').order_by('-bookmarked_at')
                )
                return HttpResponse(
                    format_html(
                        (
                            'Multiple Snapshots match the given timestamp/ID <code>{}</code><br/><pre>'
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
                            '<html><head>'
                            '<title>Snapshot Not Found</title>'
                            #'<script>'
                            #'setTimeout(() => { window.location.reload(); }, 5000);'
                            #'</script>'
                            '</head><body>'
                            '<center><br/><br/><br/>'
                            f'Snapshot <a href="/{snapshot.archive_path}/index.html" target="_top"><b><code>[{snapshot.timestamp}]</code></b></a>: <a href="{snapshot.url}" target="_blank" rel="noreferrer">{snapshot.url}</a><br/>'
                            f'was queued on {str(snapshot.bookmarked_at).split(".")[0]}, '
                            f'but no files have been saved yet in:<br/><b><a href="/{snapshot.archive_path}/" target="_top"><code>{snapshot.timestamp}</code></a><code>/'
                            '{}'
                            f'</code></b><br/><br/>'
                            'It\'s possible {} '
                            f'during the last capture on {str(snapshot.bookmarked_at).split(".")[0]},<br/>or that the archiving process has not completed yet.<br/>'
                            f'<pre><code># run this cmd to finish/retry archiving this Snapshot</code><br/>'
                            f'<code style="user-select: all; color: #333">archivebox update -t timestamp {snapshot.timestamp}</code></pre><br/><br/>'
                            '<div class="text-align: left; width: 100%; max-width: 400px">'
                            '<i><b>Next steps:</i></b><br/>'
                            f'- list all the <a href="/{snapshot.archive_path}/" target="_top">Snapshot files <code>.*</code></a><br/>'
                            f'- view the <a href="/{snapshot.archive_path}/index.html" target="_top">Snapshot <code>./index.html</code></a><br/>'
                            f'- go to the <a href="/admin/core/snapshot/{snapshot.pk}/change/" target="_top">Snapshot admin</a> to edit<br/>'
                            f'- go to the <a href="/admin/core/snapshot/?id__exact={snapshot.id}" target="_top">Snapshot actions</a> to re-archive<br/>'
                            '- or return to <a href="/" target="_top">the main index...</a></div>'
                            '</center>'
                            '</body></html>'
                        ),
                        archivefile if str(archivefile) != 'None' else '',
                        f'the {archivefile} resource could not be fetched' if str(archivefile) != 'None' else 'the original site was not available',
                    ),
                    content_type="text/html",
                    status=404,
                )
            
        # slug is a URL
        try:
            try:
                snapshot = SnapshotView.find_snapshots_for_url(path).get()
            except Snapshot.DoesNotExist:
                raise
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
            snapshots = SnapshotView.find_snapshots_for_url(path)
            snapshot_hrefs = mark_safe('<br/>').join(
                format_html(
                    '{} <code style="font-size: 0.8em">{}</code> <a href="/{}/index.html"><b><code>{}</code></b></a> {} <b>{}</b>',
                    snap.bookmarked_at.strftime('%Y-%m-%d %H:%M:%S'),
                    str(snap.id)[:8],
                    snap.archive_path,
                    snap.timestamp,
                    snap.url,
                    snap.title_stripped[:64] or '',
                )
                for snap in snapshots.only('url', 'timestamp', 'title', 'bookmarked_at').order_by('-bookmarked_at')
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

        target_path = f'/{snapshot.archive_path}/index.html'
        query = request.META.get('QUERY_STRING')
        if query:
            target_path = f'{target_path}?{query}'
        return redirect(target_path)


class SnapshotPathView(View):
    """Serve snapshots by the new URL scheme: /<username>/<YYYYMMDD>/<domain>/<uuid>/..."""

    def get(self, request, username: str, date: str, domain: str | None = None, snapshot_id: str | None = None, path: str = "", url: str | None = None):
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return redirect(f'/admin/login/?next={request.path}')

        if username == 'system':
            return redirect(request.path.replace('/system/', '/web/', 1))

        requested_url = url
        if not requested_url and domain and domain.startswith(('http://', 'https://')):
            requested_url = domain

        snapshot = None
        if snapshot_id:
            try:
                snapshot = Snapshot.objects.get(pk=snapshot_id)
            except Snapshot.DoesNotExist:
                try:
                    snapshot = Snapshot.objects.get(id__startswith=snapshot_id)
                except Snapshot.DoesNotExist:
                    snapshot = None
                except Snapshot.MultipleObjectsReturned:
                    snapshot = Snapshot.objects.filter(id__startswith=snapshot_id).first()
        else:
            # fuzzy lookup by date + domain/url (most recent)
            username_lookup = 'system' if username == 'web' else username
            if requested_url:
                qs = SnapshotView.find_snapshots_for_url(requested_url).filter(crawl__created_by__username=username_lookup)
            else:
                qs = Snapshot.objects.filter(crawl__created_by__username=username_lookup)

            try:
                if len(date) == 4:
                    qs = qs.filter(created_at__year=int(date))
                elif len(date) == 6:
                    qs = qs.filter(created_at__year=int(date[:4]), created_at__month=int(date[4:6]))
                elif len(date) == 8:
                    qs = qs.filter(
                        created_at__year=int(date[:4]),
                        created_at__month=int(date[4:6]),
                        created_at__day=int(date[6:8]),
                    )
            except ValueError:
                pass

            if requested_url:
                snapshot = qs.order_by('-created_at', '-bookmarked_at', '-timestamp').first()
            else:
                requested_domain = domain or ''
                if requested_domain.startswith(('http://', 'https://')):
                    requested_domain = Snapshot.extract_domain_from_url(requested_domain)
                else:
                    requested_domain = Snapshot.extract_domain_from_url(f'https://{requested_domain}')

                # Prefer exact domain matches
                matches = [s for s in qs.order_by('-created_at', '-bookmarked_at') if Snapshot.extract_domain_from_url(s.url) == requested_domain]
                snapshot = matches[0] if matches else qs.order_by('-created_at', '-bookmarked_at', '-timestamp').first()

        if not snapshot:
            return HttpResponse(
                format_html(
                    (
                        '<center><br/><br/><br/>'
                        'No Snapshots match the given id or url: <code>{}</code><br/><br/><br/>'
                        'Return to the <a href="/" target="_top">Main Index</a>'
                        '</center>'
                    ),
                    snapshot_id or requested_url or domain,
                ),
                content_type="text/html",
                status=404,
            )

        canonical_base = snapshot.url_path
        requested_base = f'{username}/{date}/{domain or url or ""}'
        if snapshot_id:
            requested_base = f'{requested_base}/{snapshot_id}'
        if canonical_base != requested_base:
            target = f'/{canonical_base}/{path or "index.html"}'
            query = request.META.get('QUERY_STRING')
            if query:
                target = f'{target}?{query}'
            return redirect(target)

        archivefile = path or "index.html"

        if archivefile == "index.html":
            return SnapshotView.render_live_index(request, snapshot)

        return serve_static_with_byterange_support(
            request, archivefile, document_root=snapshot.output_dir, show_indexes=True,
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
        from archivebox.core.models import Tag

        return {
            **super().get_context_data(**kwargs),
            'title': "Create Crawl",
            # We can't just call request.build_absolute_uri in the template, because it would include query parameters
            'absolute_add_path': self.request.build_absolute_uri(self.request.path),
            'VERSION': VERSION,
            'FOOTER_INFO': SERVER_CONFIG.FOOTER_INFO,
            'stdout': '',
            'available_tags': list(Tag.objects.all().order_by('name').values_list('name', flat=True)),
        }

    def form_valid(self, form):
        urls = form.cleaned_data["url"]
        print(f'[+] Adding URL: {urls}')

        # Extract all form fields
        tag = form.cleaned_data["tag"]
        depth = int(form.cleaned_data["depth"])
        plugins = ','.join(form.cleaned_data.get("plugins", []))
        schedule = form.cleaned_data.get("schedule", "").strip()
        persona = form.cleaned_data.get("persona", "Default")
        overwrite = form.cleaned_data.get("overwrite", False)
        update = form.cleaned_data.get("update", False)
        index_only = form.cleaned_data.get("index_only", False)
        notes = form.cleaned_data.get("notes", "")
        custom_config = form.cleaned_data.get("config", {})

        from archivebox.config.permissions import HOSTNAME


        # 1. save the provided urls to sources/2024-11-05__23-59-59__web_ui_add_by_user_<user_pk>.txt
        sources_file = CONSTANTS.SOURCES_DIR / f'{timezone.now().strftime("%Y-%m-%d__%H-%M-%S")}__web_ui_add_by_user_{self.request.user.pk}.txt'
        sources_file.write_text(urls if isinstance(urls, str) else '\n'.join(urls))

        # 2. create a new Crawl with the URLs from the file
        timestamp = timezone.now().strftime("%Y-%m-%d__%H-%M-%S")
        urls_content = sources_file.read_text()
        # Build complete config
        config = {
            'ONLY_NEW': not update,
            'INDEX_ONLY': index_only,
            'OVERWRITE': overwrite,
            'DEPTH': depth,
            'PLUGINS': plugins or '',
            'DEFAULT_PERSONA': persona or 'Default',
        }

        # Merge custom config overrides
        config.update(custom_config)

        crawl = Crawl.objects.create(
            urls=urls_content,
            max_depth=depth,
            tags_str=tag,
            notes=notes,
            label=f'{self.request.user.username}@{HOSTNAME}{self.request.path} {timestamp}',
            created_by_id=self.request.user.pk,
            config=config
        )

        # 3. create a CrawlSchedule if schedule is provided
        if schedule:
            from archivebox.crawls.models import CrawlSchedule
            crawl_schedule = CrawlSchedule.objects.create(
                template=crawl,
                schedule=schedule,
                is_enabled=True,
                label=crawl.label,
                notes=f"Auto-created from add page. {notes}".strip(),
                created_by_id=self.request.user.pk,
            )
            crawl.schedule = crawl_schedule
            crawl.save(update_fields=['schedule'])

        # 4. start the Orchestrator & wait until it completes
        #    ... orchestrator will create the root Snapshot, which creates pending ArchiveResults, which gets run by the ArchiveResultActors ...
        # from archivebox.crawls.actors import CrawlActor
        # from archivebox.core.actors import SnapshotActor, ArchiveResultActor


        rough_url_count = urls.count('://')

        # Build success message with schedule link if created
        schedule_msg = ""
        if schedule:
            schedule_msg = f" and <a href='{crawl.schedule.admin_change_url}'>scheduled to repeat {schedule}</a>"

        messages.success(
            self.request,
            mark_safe(f"Created crawl with {rough_url_count} starting URL(s){schedule_msg}. Snapshots will be created and archived in the background. <a href='{crawl.admin_change_url}'>View Crawl →</a>"),
        )

        # Orchestrator (managed by supervisord) will pick up the queued crawl
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


import json
from django.http import JsonResponse

def live_progress_view(request):
    """Simple JSON endpoint for live progress status - used by admin progress monitor."""
    try:
        from archivebox.workers.orchestrator import Orchestrator
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot, ArchiveResult
        from django.db.models import Case, When, Value, IntegerField

        # Get orchestrator status
        orchestrator_running = Orchestrator.is_running()
        total_workers = Orchestrator().get_total_worker_count() if orchestrator_running else 0

        # Get model counts by status
        crawls_pending = Crawl.objects.filter(status=Crawl.StatusChoices.QUEUED).count()
        crawls_started = Crawl.objects.filter(status=Crawl.StatusChoices.STARTED).count()

        # Get recent crawls (last 24 hours)
        from datetime import timedelta
        one_day_ago = timezone.now() - timedelta(days=1)
        crawls_recent = Crawl.objects.filter(created_at__gte=one_day_ago).count()

        snapshots_pending = Snapshot.objects.filter(status=Snapshot.StatusChoices.QUEUED).count()
        snapshots_started = Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED).count()

        archiveresults_pending = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.QUEUED).count()
        archiveresults_started = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.STARTED).count()
        archiveresults_succeeded = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.SUCCEEDED).count()
        archiveresults_failed = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.FAILED).count()

        # Get recently completed ArchiveResults with thumbnails (last 20 succeeded results)
        recent_thumbnails = []
        recent_results = ArchiveResult.objects.filter(
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        ).select_related('snapshot').order_by('-end_ts')[:20]

        for ar in recent_results:
            embed = ar.embed_path()
            if embed:
                # Only include results with embeddable image/media files
                ext = embed.lower().split('.')[-1] if '.' in embed else ''
                is_embeddable = ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'pdf', 'html')
                if is_embeddable or ar.plugin in ('screenshot', 'favicon', 'dom'):
                    recent_thumbnails.append({
                        'id': str(ar.id),
                        'plugin': ar.plugin,
                        'snapshot_id': str(ar.snapshot_id),
                        'snapshot_url': ar.snapshot.url[:60] if ar.snapshot else '',
                        'embed_path': embed,
                        'archive_path': f'/{ar.snapshot.archive_path}/{embed}' if ar.snapshot else '',
                        'end_ts': ar.end_ts.isoformat() if ar.end_ts else None,
                    })

        # Build hierarchical active crawls with nested snapshots and archive results
        from django.db.models import Prefetch

        active_crawls_qs = Crawl.objects.filter(
            status__in=[Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED]
        ).prefetch_related(
            'snapshot_set',
            'snapshot_set__archiveresult_set',
        ).distinct().order_by('-modified_at')[:10]

        active_crawls = []
        for crawl in active_crawls_qs:
            # Get ALL snapshots for this crawl to count status (already prefetched)
            all_crawl_snapshots = list(crawl.snapshot_set.all())

            # Count snapshots by status from ALL snapshots
            total_snapshots = len(all_crawl_snapshots)
            completed_snapshots = sum(1 for s in all_crawl_snapshots if s.status == Snapshot.StatusChoices.SEALED)
            started_snapshots = sum(1 for s in all_crawl_snapshots if s.status == Snapshot.StatusChoices.STARTED)
            pending_snapshots = sum(1 for s in all_crawl_snapshots if s.status == Snapshot.StatusChoices.QUEUED)

            # Get only ACTIVE snapshots to display (limit to 5 most recent)
            active_crawl_snapshots = [
                s for s in all_crawl_snapshots
                if s.status in [Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED]
            ][:5]

            # Count URLs in the crawl (for when snapshots haven't been created yet)
            urls_count = 0
            if crawl.urls:
                urls_count = len([u for u in crawl.urls.split('\n') if u.strip() and not u.startswith('#')])

            # Calculate crawl progress
            crawl_progress = int((completed_snapshots / total_snapshots) * 100) if total_snapshots > 0 else 0

            # Get active snapshots for this crawl (already prefetched)
            active_snapshots_for_crawl = []
            for snapshot in active_crawl_snapshots:
                # Get archive results for this snapshot (already prefetched)
                snapshot_results = snapshot.archiveresult_set.all()

                # Count in memory instead of DB queries
                total_plugins = len(snapshot_results)
                completed_plugins = sum(1 for ar in snapshot_results if ar.status == ArchiveResult.StatusChoices.SUCCEEDED)
                failed_plugins = sum(1 for ar in snapshot_results if ar.status == ArchiveResult.StatusChoices.FAILED)
                pending_plugins = sum(1 for ar in snapshot_results if ar.status == ArchiveResult.StatusChoices.QUEUED)

                # Calculate snapshot progress
                snapshot_progress = int(((completed_plugins + failed_plugins) / total_plugins) * 100) if total_plugins > 0 else 0

                # Get all extractor plugins for this snapshot (already prefetched, sort in Python)
                # Order: started first, then queued, then completed
                def plugin_sort_key(ar):
                    status_order = {
                        ArchiveResult.StatusChoices.STARTED: 0,
                        ArchiveResult.StatusChoices.QUEUED: 1,
                        ArchiveResult.StatusChoices.SUCCEEDED: 2,
                        ArchiveResult.StatusChoices.FAILED: 3,
                    }
                    return (status_order.get(ar.status, 4), ar.plugin)

                all_plugins = [
                    {
                        'id': str(ar.id),
                        'plugin': ar.plugin,
                        'status': ar.status,
                    }
                    for ar in sorted(snapshot_results, key=plugin_sort_key)
                ]

                active_snapshots_for_crawl.append({
                    'id': str(snapshot.id),
                    'url': snapshot.url[:80],
                    'status': snapshot.status,
                    'started': snapshot.modified_at.isoformat() if snapshot.modified_at else None,
                    'progress': snapshot_progress,
                    'total_plugins': total_plugins,
                    'completed_plugins': completed_plugins,
                    'failed_plugins': failed_plugins,
                    'pending_plugins': pending_plugins,
                    'all_plugins': all_plugins,
                })

            # Check if crawl can start (for debugging stuck crawls)
            can_start = bool(crawl.urls)
            urls_preview = crawl.urls[:60] if crawl.urls else None

            # Check if retry_at is in the future (would prevent worker from claiming)
            retry_at_future = crawl.retry_at > timezone.now() if crawl.retry_at else False
            seconds_until_retry = int((crawl.retry_at - timezone.now()).total_seconds()) if crawl.retry_at and retry_at_future else 0

            active_crawls.append({
                'id': str(crawl.id),
                'label': str(crawl)[:60],
                'status': crawl.status,
                'started': crawl.modified_at.isoformat() if crawl.modified_at else None,
                'progress': crawl_progress,
                'max_depth': crawl.max_depth,
                'urls_count': urls_count,
                'total_snapshots': total_snapshots,
                'completed_snapshots': completed_snapshots,
                'started_snapshots': started_snapshots,
                'failed_snapshots': 0,
                'pending_snapshots': pending_snapshots,
                'active_snapshots': active_snapshots_for_crawl,
                'can_start': can_start,
                'urls_preview': urls_preview,
                'retry_at_future': retry_at_future,
                'seconds_until_retry': seconds_until_retry,
            })

        return JsonResponse({
            'orchestrator_running': orchestrator_running,
            'total_workers': total_workers,
            'crawls_pending': crawls_pending,
            'crawls_started': crawls_started,
            'crawls_recent': crawls_recent,
            'snapshots_pending': snapshots_pending,
            'snapshots_started': snapshots_started,
            'archiveresults_pending': archiveresults_pending,
            'archiveresults_started': archiveresults_started,
            'archiveresults_succeeded': archiveresults_succeeded,
            'archiveresults_failed': archiveresults_failed,
            'active_crawls': active_crawls,
            'recent_thumbnails': recent_thumbnails,
            'server_time': timezone.now().isoformat(),
        })
    except Exception as e:
        import traceback
        return JsonResponse({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'orchestrator_running': False,
            'total_workers': 0,
            'crawls_pending': 0,
            'crawls_started': 0,
            'crawls_recent': 0,
            'snapshots_pending': 0,
            'snapshots_started': 0,
            'archiveresults_pending': 0,
            'archiveresults_started': 0,
            'archiveresults_succeeded': 0,
            'archiveresults_failed': 0,
            'active_crawls': [],
            'recent_thumbnails': [],
            'server_time': timezone.now().isoformat(),
        }, status=500)


def find_config_section(key: str) -> str:
    CONFIGS = get_all_configs()
    
    if key in CONSTANTS_CONFIG:
        return 'CONSTANT'
    matching_sections = [
        section_id for section_id, section in CONFIGS.items() if key in dict(section)
    ]
    section = matching_sections[0] if matching_sections else 'DYNAMIC'
    return section

def find_config_default(key: str) -> str:
    CONFIGS = get_all_configs()
    
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
    from typing import get_type_hints, ClassVar
    CONFIGS = get_all_configs()

    for config in CONFIGS.values():
        if hasattr(config, key):
            # Try to get from pydantic model_fields first (more reliable)
            if hasattr(config, 'model_fields') and key in config.model_fields:
                field = config.model_fields[key]
                if hasattr(field, 'annotation'):
                    try:
                        return str(field.annotation.__name__)
                    except AttributeError:
                        return str(field.annotation)

            # Fallback to get_type_hints with proper namespace
            try:
                import typing
                namespace = {
                    'ClassVar': ClassVar,
                    'Optional': typing.Optional,
                    'Union': typing.Union,
                    'List': typing.List,
                    'Dict': typing.Dict,
                    'Path': Path,
                }
                type_hints = get_type_hints(config, globalns=namespace, localns=namespace)
                try:
                    return str(type_hints[key].__name__)
                except AttributeError:
                    return str(type_hints[key])
            except Exception:
                # If all else fails, return str
                pass
    return 'str'

def key_is_safe(key: str) -> bool:
    for term in ('key', 'password', 'secret', 'token'):
        if term in key.lower():
            return False
    return True

def find_config_source(key: str, merged_config: dict) -> str:
    """Determine where a config value comes from."""
    import os
    from archivebox.machine.models import Machine

    # Check if it's from archivebox.machine.config
    try:
        machine = Machine.current()
        if machine.config and key in machine.config:
            return 'Machine'
    except Exception:
        pass

    # Check if it's from environment variable
    if key in os.environ:
        return 'Environment'

    # Check if it's from archivebox.config.file
    from archivebox.config.configset import BaseConfigSet
    file_config = BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE)
    if key in file_config:
        return 'Config File'

    # Otherwise it's using the default
    return 'Default'


@render_with_table_view
def live_config_list_view(request: HttpRequest, **kwargs) -> TableContext:
    CONFIGS = get_all_configs()

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    # Get merged config that includes Machine.config overrides
    try:
        from archivebox.machine.models import Machine
        machine = Machine.current()
        merged_config = get_config()
    except Exception as e:
        # Fallback if Machine model not available
        merged_config = get_config()
        machine = None

    rows = {
        "Section": [],
        "Key": [],
        "Type": [],
        "Value": [],
        "Source": [],
        "Default": [],
        # "Documentation": [],
        # "Aliases": [],
    }

    for section_id, section in reversed(list(CONFIGS.items())):
        for key in dict(section).keys():
            rows['Section'].append(section_id)   # section.replace('_', ' ').title().replace(' Config', '')
            rows['Key'].append(ItemLink(key, key=key))
            rows['Type'].append(format_html('<code>{}</code>', find_config_type(key)))

            # Use merged config value (includes machine overrides)
            actual_value = merged_config.get(key, getattr(section, key, None))
            rows['Value'].append(mark_safe(f'<code>{actual_value}</code>') if key_is_safe(key) else '******** (redacted)')

            # Show where the value comes from
            source = find_config_source(key, merged_config)
            source_colors = {
                'Machine': 'purple',
                'Environment': 'blue',
                'Config File': 'green',
                'Default': 'gray'
            }
            rows['Source'].append(format_html('<code style="color: {}">{}</code>', source_colors.get(source, 'gray'), source))

            rows['Default'].append(mark_safe(f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code"><code style="text-decoration: underline">{find_config_default(key) or "See here..."}</code></a>'))
            # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
            # rows['Aliases'].append(', '.join(find_config_aliases(key)))

    section = 'CONSTANT'
    for key in CONSTANTS_CONFIG.keys():
        rows['Section'].append(section)   # section.replace('_', ' ').title().replace(' Config', '')
        rows['Key'].append(ItemLink(key, key=key))
        rows['Type'].append(format_html('<code>{}</code>', getattr(type(CONSTANTS_CONFIG[key]), '__name__', str(CONSTANTS_CONFIG[key]))))
        rows['Value'].append(format_html('<code>{}</code>', CONSTANTS_CONFIG[key]) if key_is_safe(key) else '******** (redacted)')
        rows['Source'].append(mark_safe('<code style="color: gray">Constant</code>'))
        rows['Default'].append(mark_safe(f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code"><code style="text-decoration: underline">{find_config_default(key) or "See here..."}</code></a>'))
        # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
        # rows['Aliases'].append('')


    return TableContext(
        title="Computed Configuration Values",
        table=rows,
    )

@render_with_item_view
def live_config_value_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    import os
    from archivebox.machine.models import Machine
    from archivebox.config.configset import BaseConfigSet

    CONFIGS = get_all_configs()
    FLAT_CONFIG = get_flat_config()

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    # Get merged config
    merged_config = get_config()

    # Determine all sources for this config value
    sources_info = []

    # Default value
    default_val = find_config_default(key)
    if default_val:
        sources_info.append(('Default', default_val, 'gray'))

    # Config file value
    if CONSTANTS.CONFIG_FILE.exists():
        file_config = BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE)
        if key in file_config:
            sources_info.append(('Config File', file_config[key], 'green'))

    # Environment variable
    if key in os.environ:
        sources_info.append(('Environment', os.environ[key] if key_is_safe(key) else '********', 'blue'))

    # Machine config
    machine = None
    machine_admin_url = None
    try:
        machine = Machine.current()
        machine_admin_url = f'/admin/machine/machine/{machine.id}/change/'
        if machine.config and key in machine.config:
            sources_info.append(('Machine', machine.config[key] if key_is_safe(key) else '********', 'purple'))
    except Exception:
        pass

    # Final computed value
    final_value = merged_config.get(key, FLAT_CONFIG.get(key, CONFIGS.get(key, None)))
    if not key_is_safe(key):
        final_value = '********'

    # Build sources display
    sources_html = '<br/>'.join([
        f'<b style="color: {color}">{source}:</b> <code>{value}</code>'
        for source, value, color in sources_info
    ])

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
                    'Value': final_value,
                    'Source': find_config_source(key, merged_config),
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
                        <b>Configuration Sources (in priority order):</b><br/><br/>
                        {sources_html}
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
                    'Source': mark_safe(f'''
                        The value shown in the "Value" field comes from the <b>{find_config_source(key, merged_config)}</b> source.
                        <br/><br/>
                        Priority order (highest to lowest):
                        <ol>
                            <li><b style="color: purple">Machine</b> - Machine-specific overrides (e.g., resolved binary paths)
                                {f'<br/><a href="{machine_admin_url}">→ Edit <code>{key}</code> in Machine.config for this server</a>' if machine_admin_url else ''}
                            </li>
                            <li><b style="color: blue">Environment</b> - Environment variables</li>
                            <li><b style="color: green">Config File</b> - data/ArchiveBox.conf</li>
                            <li><b style="color: gray">Default</b> - Default value from code</li>
                        </ol>
                        {f'<br/><b>💡 Tip:</b> To override <code>{key}</code> on this machine, <a href="{machine_admin_url}">edit the Machine.config field</a> and add:<br/><code>{{"\\"{key}\\": "your_value_here"}}</code>' if machine_admin_url and key not in CONSTANTS_CONFIG else ''}
                    '''),
                },
            },
        ],
    )

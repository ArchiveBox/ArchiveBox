__package__ = 'archivebox.core'

from io import StringIO
from contextlib import redirect_stdout

from django.shortcuts import render, redirect

from django.http import HttpResponse
from django.views import View, static
from django.views.generic.list import ListView
from django.views.generic import FormView
from django.contrib.auth.mixins import UserPassesTestMixin

from core.models import Snapshot
from core.utils import get_icons
from core.forms import AddLinkForm

from ..config import (
    OUTPUT_DIR,
    PUBLIC_INDEX,
    PUBLIC_SNAPSHOTS,
    PUBLIC_ADD_VIEW
)
from main import add
from ..util import base_url, ansi_to_html


class MainIndex(View):
    template = 'main_index.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/admin/core/snapshot/')

        if PUBLIC_INDEX:
            return redirect('public-index')
        
        return redirect(f'/admin/login/?next={request.path}')


class LinkDetails(View):
    def get(self, request, path):
        # missing trailing slash -> redirect to index
        if '/' not in path:
            return redirect(f'{path}/index.html')

        if not request.user.is_authenticated and not PUBLIC_SNAPSHOTS:
            return redirect(f'/admin/login/?next={request.path}')

        try:
            slug, archivefile = path.split('/', 1)
        except (IndexError, ValueError):
            slug, archivefile = path.split('/', 1)[0], 'index.html'

        all_pages = list(Snapshot.objects.all())

        # slug is a timestamp
        by_ts = {page.timestamp: page for page in all_pages}
        try:
            # print('SERVING STATICFILE', by_ts[slug].link_dir, request.path, path)
            response = static.serve(request, archivefile, document_root=by_ts[slug].link_dir, show_indexes=True)
            response["Link"] = f'<{by_ts[slug].url}>; rel="canonical"'
            return response
        except KeyError:
            pass

        # slug is a hash
        by_hash = {page.url_hash: page for page in all_pages}
        try:
            timestamp = by_hash[slug].timestamp
            return redirect(f'/archive/{timestamp}/{archivefile}')
        except KeyError:
            pass

        # slug is a URL
        by_url = {page.base_url: page for page in all_pages}
        try:
            # TODO: add multiple snapshot support by showing index of all snapshots
            # for given url instead of redirecting to timestamp index
            timestamp = by_url[base_url(path)].timestamp
            return redirect(f'/archive/{timestamp}/index.html')
        except KeyError:
            pass

        return HttpResponse(
            'No archived link matches the given timestamp or hash.',
            content_type="text/plain",
            status=404,
        )

class PublicArchiveView(ListView):
    template = 'snapshot_list.html'
    model = Snapshot
    paginate_by = 100

    def get_queryset(self, **kwargs): 
        qs = super().get_queryset(**kwargs) 
        query = self.request.GET.get('q')
        if query:
            qs = Snapshot.objects.filter(title__icontains=query)
        for snapshot in qs:
            snapshot.icons = get_icons(snapshot) 
        return qs

    def get(self, *args, **kwargs):
        if PUBLIC_INDEX or self.request.user.is_authenticated:
            response = super().get(*args, **kwargs)
            return response
        else:
            return redirect(f'/admin/login/?next={self.request.path}')


class AddView(UserPassesTestMixin, FormView):
    template_name = "add_links.html"
    form_class = AddLinkForm

    def test_func(self):
        return PUBLIC_ADD_VIEW or self.request.user.is_authenticated

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["title"] = "Add URLs"
        return context

    def form_valid(self, form):
        url = form.cleaned_data["url"]
        print(f'[+] Adding URL: {url}')
        depth = 0 if form.cleaned_data["depth"] == "0" else 1
        input_kwargs = {
            "urls": url,
            "depth": depth,
            "update_all": False,
            "out_dir": OUTPUT_DIR,
        }
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

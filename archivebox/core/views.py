__package__ = 'archivebox.core'

from django.shortcuts import render, redirect

from django.http import HttpResponse
from django.views import View, static
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin

from core.models import Snapshot

from contextlib import redirect_stdout
from io import StringIO

from ..index import load_main_index, load_main_index_meta
from ..config import (
    OUTPUT_DIR,
    VERSION,
    FOOTER_INFO,
    PUBLIC_INDEX,
    PUBLIC_SNAPSHOTS,
)
from ..util import base_url, ansi_to_html
from .. main import add

from .forms import AddLinkForm


class MainIndex(LoginRequiredMixin, View):
    template = 'main_index.html'

    def get(self, request):
        if not request.user.is_authenticated and not PUBLIC_INDEX:
            return redirect(f'/admin/login/?next={request.path}')

        all_links = load_main_index(out_dir=OUTPUT_DIR)
        meta_info = load_main_index_meta(out_dir=OUTPUT_DIR)

        context = {
            'updated': meta_info['updated'],
            'num_links': meta_info['num_links'],
            'links': all_links,
            'VERSION': VERSION,
            'FOOTER_INFO': FOOTER_INFO,
        }

        return render(template_name=self.template, request=request, context=context)


class AddLinks(LoginRequiredMixin, View):
    template = 'add_links.html'

    def get(self, request):
        if not request.user.is_authenticated and not PUBLIC_INDEX:
            return redirect(f'/admin/login/?next={request.path}')

        context = {
            "form": AddLinkForm()
        }

        return render(template_name=self.template, request=request, context=context)

    def post(self, request):
        form = AddLinkForm(request.POST)
        if form.is_valid():
            url = form.cleaned_data["url"]
            print(f'[+] Adding URL: {url}')
            if form.cleaned_data["source"] == "url":
                key = "import_str"
            else:
                key = "import_path"
            input_kwargs = {
                key: url,
                "update_all": False,
                "out_dir": OUTPUT_DIR,
            }
            add_stdout = StringIO()
            with redirect_stdout(add_stdout):
                extracted_links = add(**input_kwargs)
            print(add_stdout.getvalue())

            context = {
                "stdout": ansi_to_html(add_stdout.getvalue()),
                "form": AddLinkForm()
            }
        else:
            context = {"form": form}

        return render(template_name=self.template, request=request, context=context)


class LinkDetails(LoginRequiredMixin, View):
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
            return static.serve(request, archivefile, by_ts[slug].link_dir, show_indexes=True)
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

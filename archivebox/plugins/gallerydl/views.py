import os
import sys
from pathlib import Path

from django.views import View
from django.shortcuts import render
from django.db.models import Q

from core.models import Snapshot

# from archivebox.config import PUBLIC_SNAPSHOTS
PUBLIC_SNAPSHOTS = True


class GalleryDLIconView(View):
    template_name = 'plugin_gallerydl__icon.html'

    # render static html index from filesystem archive/<timestamp>/index.html

    def get_context_data(self, **kwargs):
        return {
            # **super().get_context_data(**kwargs),
            # 'VERSION': VERSION,
            # 'COMMIT_HASH': COMMIT_HASH,
            # 'FOOTER_INFO': FOOTER_INFO,
        }


    def get(self, request, path):
        if not request.user.is_authenticated and not PUBLIC_SNAPSHOTS:
            return redirect(f'/admin/login/?next={request.path}')

        # ...
        return render(template_name=self.template_name, request=self.request, context=context)


class GalleryDLEmbedView(View):
    template_name = 'plugin_gallerydl__embed.html'

    # render static html index from filesystem archive/<timestamp>/index.html

    def get_context_data(self, **kwargs):
        return {
            # **super().get_context_data(**kwargs),
            # 'VERSION': VERSION,
            # 'COMMIT_HASH': COMMIT_HASH,
            # 'FOOTER_INFO': FOOTER_INFO,
        }


    def get(self, request, path):
        if not request.user.is_authenticated and not PUBLIC_SNAPSHOTS:
            return redirect(f'/admin/login/?next={request.path}')

        # ...
        return render(template_name=self.template_name, request=self.request, context=context)


class GalleryDLOutputView(View):
    template_name = 'plugin_gallerydl__output.html'

    # render static html index from filesystem archive/<timestamp>/index.html

    def get_context_data(self, **kwargs):
        return {
            # **super().get_context_data(**kwargs),
            # 'VERSION': VERSION,
            # 'COMMIT_HASH': COMMIT_HASH,
            # 'FOOTER_INFO': FOOTER_INFO,
        }


    def get(self, request, path):
        if not request.user.is_authenticated and not PUBLIC_SNAPSHOTS:
            return redirect(f'/admin/login/?next={request.path}')

        # ...
        return render(template_name=self.template_name, request=self.request, context=context)

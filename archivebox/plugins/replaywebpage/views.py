import os
import sys
from pathlib import Path

from django.views import View
from django.shortcuts import render
from django.db.models import Q

from core.models import Snapshot

# from archivebox.config import PUBLIC_SNAPSHOTS
PUBLIC_SNAPSHOTS = True


class ReplayWebPageViewer(View):
    template_name = 'plugin_replaywebpage__viewer.html'

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

        try:
            timestamp, warc_filename = path.split('/', 1)
        except (IndexError, ValueError):
            timestamp, warc_filename = path.split('/', 1)[0], ''

        snapshot = Snapshot.objects.get(Q(timestamp=timestamp) | Q(id__startswith=timestamp))

        context = self.get_context_data()
        context.update({
            "snapshot": snapshot,
            "timestamp": timestamp,
            "warc_filename": warc_filename,
        })
        return render(template_name=self.template_name, request=self.request, context=context)


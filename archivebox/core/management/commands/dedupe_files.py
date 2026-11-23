from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from archivebox.core.models import Snapshot
from archivebox.core.collection_dedupe import deduplicate_sealed


class Command(BaseCommand):
    help = "Deduplicate files from completed hash manifests in sealed snapshots."

    def handle(self, *args, **options):
        counts = Counter()
        snapshots = Snapshot.objects.filter(status="sealed", retry_at__isnull=True).order_by("pk")
        ids = snapshots.values_list("pk", flat=True)
        while page := list(ids[:500]):
            for pk in page:
                counts.update(deduplicate_sealed(pk))
            ids = snapshots.filter(pk__gt=page[-1]).values_list("pk", flat=True)
        self.stdout.write(str(dict(counts)))
        if counts["errors"]:
            raise CommandError("Some manifests could not be processed. See the snapshot errors above.")

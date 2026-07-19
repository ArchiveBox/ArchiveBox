from django.utils import timezone

from archivebox.workers.models import RETRY_AT_MAX


def test_retry_at_max_is_safe_for_admin_timezone_localization():
    with timezone.override("Pacific/Kiritimati"):
        assert timezone.localtime(RETRY_AT_MAX).year == 9999

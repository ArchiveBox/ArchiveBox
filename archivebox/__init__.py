__package__ = 'archivebox'


# monkey patch django timezone to add back utc (it was removed in Django 5.0)
import datetime
from django.utils import timezone
timezone.utc = datetime.timezone.utc

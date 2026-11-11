from django.db import models
from django.urls import reverse


class SiteClone(models.Model):
    """A whole-site capture is an ordinary Crawl with its own setup surface."""

    crawl = models.OneToOneField("crawls.Crawl", primary_key=True, on_delete=models.CASCADE, related_name="site_clone")

    def get_absolute_url(self):
        return reverse("siteclones:detail", args=[self.pk])

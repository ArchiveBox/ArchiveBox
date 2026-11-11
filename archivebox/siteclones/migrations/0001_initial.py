from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("crawls", "0019_crawlschedule_config")]
    operations = [
        migrations.CreateModel(
            name="SiteClone",
            fields=[
                (
                    "crawl",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="site_clone",
                        serialize=False,
                        to="crawls.crawl",
                    ),
                ),
            ],
        ),
    ]

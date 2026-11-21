from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("crawls", "0020_crawl_folder")]
    operations = [
        migrations.AlterModelOptions(
            name="crawl",
            options={"verbose_name": "Crawl Job", "verbose_name_plural": "Crawl Jobs"},
        ),
    ]

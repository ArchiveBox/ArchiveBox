from .hookspec import hookspec


@hookspec
def get_urlpatterns():
    return []     # e.g. [path('your_plugin_type/plugin_name/url.py', your_view)]

@hookspec
def register_urlpatterns(urlpatterns):
    """Mutate urlpatterns in place to add your urlpatterns in a specific position"""
    # e.g. urlpatterns.insert(0, path('your_plugin_type/plugin_name/url.py', your_view))
    pass

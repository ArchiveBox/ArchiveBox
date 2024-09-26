from .hookspec import hookspec
    
@hookspec
def ready(settings):
    """Called when the Django app.ready() is triggered"""
    pass

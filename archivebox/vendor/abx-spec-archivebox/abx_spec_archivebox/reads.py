__package__ = 'abx.archivebox'


from benedict import benedict


def get_scope_config(defaults: benedict | None = None, persona=None, seed=None, crawl=None, snapshot=None, archiveresult=None, extra_config=None):
    """Get all the relevant config for the given scope, in correct precedence order"""
    
    from django.conf import settings
    default_config: benedict = defaults or settings.CONFIG
    
    snapshot = snapshot or (archiveresult and archiveresult.snapshot)
    crawl = crawl or (snapshot and snapshot.crawl)
    seed = seed or (crawl and crawl.seed)
    persona = persona or (crawl and crawl.persona)
    
    persona_config = persona.config if persona else {}
    seed_config = seed.config if seed else {}
    crawl_config = crawl.config if crawl else {}
    snapshot_config = snapshot.config if snapshot else {}
    archiveresult_config = archiveresult.config if archiveresult else {}
    extra_config = extra_config or {}
    
    return benedict({
        **default_config,               # defaults / config file / environment variables
        **persona_config,               # lowest precedence
        **seed_config,
        **crawl_config,
        **snapshot_config,
        **archiveresult_config,
        **extra_config,                 # highest precedence
    })

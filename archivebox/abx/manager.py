import inspect

import pluggy


class PluginManager(pluggy.PluginManager):
    """
    Patch to fix pluggy's PluginManager to work with pydantic models.
    See: https://github.com/pytest-dev/pluggy/pull/536
    """
    def parse_hookimpl_opts(self, plugin, name: str) -> pluggy.HookimplOpts | None:
        # IMPORTANT: @property methods can have side effects, and are never hookimpl
        # if attr is a property, skip it in advance
        plugin_class = plugin if inspect.isclass(plugin) else type(plugin)
        if isinstance(getattr(plugin_class, name, None), property):
            return None

        # pydantic model fields are like attrs and also can never be hookimpls
        plugin_is_pydantic_obj = hasattr(plugin, "__pydantic_core_schema__")
        if plugin_is_pydantic_obj and name in getattr(plugin, "model_fields", {}):
            # pydantic models mess with the class and attr __signature__
            # so inspect.isroutine(...) throws exceptions and cant be used
            return None
        
        try:
            return super().parse_hookimpl_opts(plugin, name)
        except AttributeError:
            return super().parse_hookimpl_opts(type(plugin), name)

pm = PluginManager("abx")

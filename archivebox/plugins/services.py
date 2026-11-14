"""Run plugin-declared collection services through the existing supervisor."""

import re
import time
from collections.abc import Mapping

from archivebox.plugins.discovery import get_plugin_apps, get_plugin_name


def get_plugin_services(config, *, context=None, plugin_names=None):
    if plugin_names is not None:
        plugin_names = {get_plugin_name(name) for name in plugin_names}
    from archivebox.plugins.host import host

    services = {}
    for plugin, app in get_plugin_apps().items():
        if plugin_names is not None and plugin not in plugin_names:
            continue
        declarations = getattr(app, "get_services", None)
        for service in declarations(host, config) if declarations else ():
            if not isinstance(service, Mapping):
                raise ValueError(f"Invalid service declaration in {plugin}")
            if set(service) - {"name", "label", "prepare", "ready", "bind", "contexts", "process_name", "identity"}:
                raise ValueError(f"Unknown service fields in {plugin}")
            name = service.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not callable(service.get("prepare")):
                raise ValueError(f"Invalid service declaration in {plugin}")
            if not isinstance(service.get("label"), str) or not service["label"]:
                raise ValueError(f"Service {name} requires a label")
            if service.get("ready") is not None and not callable(service["ready"]):
                raise ValueError(f"Invalid readiness probe for {name}")
            if service.get("bind") is not None:
                if not isinstance(service["bind"], (tuple, list)) or len(service["bind"]) != 2:
                    raise ValueError(f"Invalid bind address for {name}")
                bind_host, port = service["bind"]
                if not isinstance(bind_host, str) or not bind_host or type(port) is not int or not 0 < port < 65536:
                    raise ValueError(f"Invalid bind address for {name}")
            contexts = service.get("contexts", ("server", "runner", "command"))
            if not isinstance(contexts, (tuple, list)) or any(value not in {"server", "runner", "command"} for value in contexts):
                raise ValueError(f"Invalid startup contexts for {name}")
            identity = service.get("identity", ())
            if not isinstance(identity, (tuple, list)) or any(not isinstance(value, str) or not value for value in identity):
                raise ValueError(f"Invalid process identity for {name}")
            if service.get("process_name") is not None and not isinstance(service["process_name"], str):
                raise ValueError(f"Invalid process name for {name}")
            if context is not None and context not in contexts:
                continue
            if name in services:
                raise ValueError(f"Duplicate plugin service: {name}")
            services[name] = {**service, "plugin": plugin}
    return services


def prepare_service_worker(service):
    worker = service["prepare"]()
    if not isinstance(worker, dict) or worker.get("name") != service["name"]:
        raise ValueError(f"Service worker name changed: {service['name']}")
    metadata = {key: service[key] for key in ("label", "bind", "process_name", "identity") if key in service}
    return {**worker, "service": metadata}


def plugin_service_workers(config, *, context, supervisor=None, plugin_names=None):
    from archivebox.workers.supervisord_util import get_worker

    workers = []
    for service in get_plugin_services(config, context=context, plugin_names=plugin_names).values():
        current = get_worker(supervisor, service["name"]) if supervisor is not None else None
        if (
            service.get("ready")
            and service["ready"]()
            and not (isinstance(current, dict) and current.get("statename") in {"STARTING", "RUNNING"})
        ):
            continue
        workers.append(prepare_service_worker(service))
    return workers


def ensure_plugin_services(config, *, plugin_names=None, reason=""):
    from archivebox.workers.supervisord_util import (
        get_existing_supervisord_process,
        get_or_create_supervisord_process,
        get_worker,
        start_worker,
    )

    workers = []
    for service in get_plugin_services(config, context="command", plugin_names=plugin_names).values():
        ready = service.get("ready")
        if ready and ready():
            workers.append({"name": service["name"], "statename": "RUNNING"})
            continue
        worker_spec = prepare_service_worker(service)
        supervisor = get_existing_supervisord_process() or get_or_create_supervisord_process(daemonize=False)
        worker = get_worker(supervisor, service["name"])
        if not (isinstance(worker, dict) and worker.get("statename") in {"STARTING", "RUNNING"}):
            worker = start_worker(supervisor, worker_spec)
        if ready:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                if ready():
                    break
                worker = get_worker(supervisor, service["name"])
                if not isinstance(worker, dict) or worker.get("statename") not in {"STARTING", "RUNNING"}:
                    raise RuntimeError(f"{service['label']} service failed to start for {reason or 'command'}: {worker}")
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            else:
                raise RuntimeError(f"{service['label']} service is not ready for {reason or 'command'}")
        workers.append(worker)
    return workers

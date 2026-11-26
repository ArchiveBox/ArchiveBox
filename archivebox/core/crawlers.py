"""Allow user-directed assistants while limiting bulk crawlers and training."""

import re
from inspect import iscoroutinefunction

from django.http import HttpResponse, HttpResponseForbidden
from django.utils.cache import patch_vary_headers
from django.utils.decorators import sync_and_async_middleware

from archivebox.plugins.discovery import get_plugin_catalog


# Content signals express usage policy; reject known training/dataset fetchers
# at request time without confusing them with each provider's user assistants.
TRAINING_USER_AGENT = re.compile(
    r"(?<![\w-])(?:GPTBot|ClaudeBot|MistralAI-Training|meta-externalagent|CCBot)(?=/|[\s;)]|$)",
    re.IGNORECASE,
)
ASSISTANT_USER_AGENT = re.compile(
    r"(?<![\w-])(?:Perplexity-User|Google-Agent|Google-GeminiNotebook|Google-NotebookLM|"
    r"ChatGPT-User|Claude-User|Claude-Agent|meta-externalfetcher|MistralAI-User|Amzn-User|Kimi-User)(?=/|[\s;)]|$)",
    re.IGNORECASE,
)

# Crawler families and user-triggered fetchers documented by their operators.
# Generic bot/spider/crawler identifiers cover additional self-declared robots;
# ordinary browser, curl, wget, requests and httpx user agents remain unchanged.
CRAWLER_USER_AGENT = re.compile(
    r"bot\b|bot[-_/]|spider|crawler|facebookexternalhit|meta-external|meta-webindexer|"
    r"ChatGPT-User|Claude-(?:User|Agent)|Kimi-User|Amzn-User|Perplexity-User|"
    r"MistralAI-(?:Index|Training|User)|BingPreview|MicrosoftPreview|"
    r"Google-(?:Agent|GeminiNotebook|NotebookLM|Read-Aloud|Pinpoint|InspectionTool|Site-Verification|CWS)|"
    r"GoogleOther|GoogleMessages|GoogleProducer|FeedFetcher-Google|Mediapartners-Google|APIs-Google|Google-Safety",
    re.IGNORECASE,
)
SNAPSHOT_ID = r"[0-9a-fA-F-]{8,36}"
SNAPSHOT_HOST = re.compile(rf"^snap-{SNAPSHOT_ID}(?:\.|:|$)", re.IGNORECASE)
PREFIXES = (
    "",
    rf"snapshot/{SNAPSHOT_ID}/",
    rf"[^/]+/\d{{4}}(?:\d{{2}})?(?:\d{{2}})?/[^/]+/{SNAPSHOT_ID}/",
)


@sync_and_async_middleware
def CrawlerMiddleware(get_response):
    # Startup-only catalog lookup. Refused requests do not consult Machine,
    # sessions, ArchiveResults, or the archive filesystem.
    outputs = tuple(
        f"{plugin.name}/{path}" for plugin in get_plugin_catalog().values() for path in plugin.manifest.get("crawler_output_paths", [])
    )
    suffix = "(?:" + "|".join(re.escape(path) for path in outputs) + ")" if outputs else r"(?!)"
    direct_path = re.compile(rf"^/{suffix}$")
    snapshot_path = re.compile(rf"^/(?:{'|'.join(PREFIXES[1:])}){suffix}$")
    robots = "User-agent: *\nDisallow: /\n"
    robots += "Content-signal: search=no, ai-input=yes, ai-train=no, use=reference\n"

    def inspect(request):
        if request.path == "/robots.txt":
            response = HttpResponse(robots, content_type="text/plain; charset=utf-8")
            response["Cache-Control"] = "public, max-age=300"
            return response, False
        if request.path in {"/health", "/health/"}:
            return None, False
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        is_training = bool(TRAINING_USER_AGENT.search(user_agent))
        is_assistant = not is_training and bool(ASSISTANT_USER_AGENT.search(user_agent))
        is_crawler = bool(CRAWLER_USER_AGENT.search(user_agent))
        if not is_training and (request.path == "/favicon.ico" or request.path.startswith("/static/")):
            if not is_crawler or (
                request.method in {"GET", "HEAD"} and not {"download", "preview", "thumbnail", "files"}.intersection(request.GET)
            ):
                return None, True
        safe_path = bool(
            snapshot_path.fullmatch(request.path) or (SNAPSHOT_HOST.match(request.get_host()) and direct_path.fullmatch(request.path)),
        )
        safe_query = (
            not (set(request.GET) - {"raw", "_abx_rev"})
            and ("raw" not in request.GET or request.GET.getlist("raw") == ["1"])
            and ("_abx_rev" not in request.GET or len(request.GET.getlist("_abx_rev")) == 1)
        )
        safe = safe_path and safe_query and request.method in {"GET", "HEAD"}
        if not is_training and (not is_crawler or (is_assistant and not safe)):
            # Human replay responses must not be cached and served to blocked bots.
            return None, True
        if is_training or not safe:
            response = HttpResponseForbidden(
                "AI training crawlers are not permitted.\n" if is_training else "Crawlers may only request declared static HTML outputs.\n",
                content_type="text/plain",
            )
            response["X-Robots-Tag"] = "noindex, follow"
            response["Cache-Control"] = "private, no-store"
            patch_vary_headers(response, ("User-Agent",))
            return response, False
        # Use the existing raw-file behavior, without changing the public URL.
        request.GET = request.GET.copy()
        request.GET["raw"] = "1"
        request.archivebox_crawler_raw = True
        return None, True

    if iscoroutinefunction(get_response):

        async def middleware(request):
            response, vary = inspect(request)
            if response is None:
                response = await get_response(request)
            response["X-Robots-Tag"] = "noindex, follow"
            if vary:
                patch_vary_headers(response, ("User-Agent",))
            return response

    else:

        def middleware(request):
            response, vary = inspect(request)
            if response is None:
                response = get_response(request)
            response["X-Robots-Tag"] = "noindex, follow"
            if vary:
                patch_vary_headers(response, ("User-Agent",))
            return response

    return middleware

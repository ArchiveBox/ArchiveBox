__package__ = "archivebox.api"

from django.http import HttpResponse


class ApiCorsMiddleware:
    """Attach permissive CORS headers for API routes (token-based auth)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/"):
            if request.method == "OPTIONS" and request.META.get("HTTP_ACCESS_CONTROL_REQUEST_METHOD"):
                response = HttpResponse(status=204)
                return self._add_cors_headers(request, response)

            response = self.get_response(request)
            return self._add_cors_headers(request, response)

        return self.get_response(request)

    def _add_cors_headers(self, request, response):
        origin = request.META.get("HTTP_ORIGIN")
        if not origin:
            return response

        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Authorization, X-ArchiveBox-API-Key, Content-Type, X-CSRFToken"
        response["Access-Control-Max-Age"] = "600"
        return response

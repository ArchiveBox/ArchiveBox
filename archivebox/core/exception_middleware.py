__package__ = "archivebox.core"

import re
from urllib.parse import urlparse

from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render
from django.core.exceptions import ValidationError
from django.forms import ValidationError as FormValidationError

from archivebox.misc.util import URL_REGEX, find_all_urls


class InvalidURLError(Exception):
    def __init__(self, message: str, invalid_url: str | None = None):
        self.message = message
        self.invalid_url = invalid_url
        super().__init__(self.message)


def is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    if not url:
        return False
    
    if not re.match(r'^https?://', url, re.IGNORECASE):
        return False
    
    urls = list(find_all_urls(url))
    return len(urls) > 0 and urls[0] == url


def is_api_request(request: HttpRequest) -> bool:
    return request.path.startswith('/api/')


def get_invalid_url_from_exception(exception: Exception) -> str | None:
    if isinstance(exception, InvalidURLError):
        return exception.invalid_url
    
    if isinstance(exception, (ValidationError, FormValidationError)):
        if hasattr(exception, 'messages'):
            for msg in exception.messages:
                urls = list(find_all_urls(str(msg)))
                if urls:
                    return urls[0]
    
    return None


class GlobalExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)
    
    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        is_400_error = False
        error_message = str(exception)
        invalid_url = get_invalid_url_from_exception(exception)
        
        if isinstance(exception, InvalidURLError):
            is_400_error = True
            error_message = exception.message
        
        elif isinstance(exception, (ValidationError, FormValidationError)):
            error_str = str(exception).lower()
            if 'url' in error_str and ('invalid' in error_str or 'valid' in error_str):
                is_400_error = True
            elif 'enter at least one valid url' in error_str:
                is_400_error = True
        
        if is_400_error:
            if is_api_request(request):
                return self._handle_api_error(request, exception, error_message, invalid_url)
            else:
                return self._handle_html_error(request, exception, error_message, invalid_url)
        
        return None
    
    def _handle_api_error(
        self, 
        request: HttpRequest, 
        exception: Exception, 
        error_message: str, 
        invalid_url: str | None
    ) -> JsonResponse:
        response_data = {
            "error": "Bad Request",
            "status_code": 400,
            "message": error_message,
            "detail": "The URL you provided is invalid.",
        }
        
        if invalid_url:
            response_data["invalid_url"] = invalid_url
        
        return JsonResponse(response_data, status=400)
    
    def _handle_html_error(
        self, 
        request: HttpRequest, 
        exception: Exception, 
        error_message: str, 
        invalid_url: str | None
    ) -> HttpResponse:
        context = {
            "error_message": error_message,
            "invalid_url": invalid_url,
            "title": "400 - Bad Request",
        }
        
        response = render(
            request,
            'core/400.html',
            context=context,
            status=400
        )
        
        return response

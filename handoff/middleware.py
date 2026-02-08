import logging

logger = logging.getLogger("handoff.proxy-headers")


class ProxyHeaderLoggingMiddleware:
    """Log what host/scheme Django sees so we can confirm proxy headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        forwarded_proto = request.META.get("HTTP_X_FORWARDED_PROTO")
        forwarded_host = request.META.get("HTTP_X_FORWARDED_HOST")
        raw_host = request.META.get("HTTP_HOST")
        logger.info(
            "Proxy headers: get_host=%s raw_host=%s scheme=%s secure=%s X_FORWARDED_PROTO=%s X_FORWARDED_HOST=%s",
            request.get_host(),
            raw_host,
            request.scheme,
            request.is_secure(),
            forwarded_proto,
            forwarded_host,
        )
        return self.get_response(request)

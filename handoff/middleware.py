import logging

logger = logging.getLogger("handoff.proxy-headers")


class ProxyHeaderLoggingMiddleware:
    """Log what host/scheme Django sees so we can confirm proxy headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        forwarded_proto = request.META.get("HTTP_X_FORWARDED_PROTO")
        logger.info(
            "Proxy headers: host=%s scheme=%s secure=%s X_FORWARDED_PROTO=%s",
            request.get_host(),
            request.scheme,
            request.is_secure(),
            forwarded_proto,
        )
        return self.get_response(request)

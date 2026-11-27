from time import perf_counter

from fastapi import Response
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST


def instrument(app):
    registry = CollectorRegistry()
    requests = Counter(
        "indusense_http_requests_total",
        "Requêtes HTTP traitées",
        ["method", "route", "status"],
        registry=registry,
    )
    duration = Histogram(
        "indusense_http_request_duration_seconds",
        "Durée des requêtes HTTP",
        ["method", "route"],
        registry=registry,
    )

    @app.middleware("http")
    async def observe(request, call_next):
        start = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            if path != "/api/metrics":
                requests.labels(request.method, path, str(status)).inc()
                duration.labels(request.method, path).observe(perf_counter() - start)

    @app.get("/api/metrics", include_in_schema=False)
    def metrics():
        return Response(
            generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

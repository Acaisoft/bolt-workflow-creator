import falcon

from src.resources import HealthCheckResource
from src.resources import WorkflowsResource
from src.services import KubernetesService
from src.services import KubernetesServiceABC


def create_app(kubernetes_service: KubernetesServiceABC):
    app = falcon.API()
    app.add_route("/health-check", HealthCheckResource())
    app.add_route("/workflows", WorkflowsResource(kubernetes_service))
    return app


def serve_app():
    kubernetes_service = KubernetesService()
    return create_app(kubernetes_service)

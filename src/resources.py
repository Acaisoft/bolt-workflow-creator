import logging

import falcon

from src.argo import create_argo_workflow
from src.schemas import WorkflowSchema
from src.services import KubernetesServiceABC


logger = logging.getLogger()


class HealthCheckResource:
    def on_get(self, request, response):
        response.media = {"status": "ok"}


class WorkflowsResource:
    def __init__(self, kubernetes_service: KubernetesServiceABC):
        self.kubernetes_service = kubernetes_service

    def on_post(self, request: falcon.Request, response: falcon.Response):
        logger.info("TEST")
        schema = WorkflowSchema()
        result = schema.load(request.media)

        if result.errors:
            raise falcon.HTTPBadRequest(result.errors)

        workflow = result.data
        argo_workflow = create_argo_workflow(workflow)

        output = self.kubernetes_service.create_argo_workflow(argo_workflow)

        response.media = output["metadata"]
        response.status = falcon.HTTP_OK

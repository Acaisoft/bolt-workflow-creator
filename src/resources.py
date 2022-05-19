import falcon

from src import custom_logger
from src.argo import create_argo_workflow
from src.schemas import WorkflowSchema
from src.services import KubernetesServiceABC


logger = custom_logger.setup_custom_logger(__file__)


class HealthCheckResource:
    def on_get(self, request, response):
        response.media = {"status": "ok"}


class WorkflowsResource:
    def __init__(self, kubernetes_service: KubernetesServiceABC):
        self.kubernetes_service = kubernetes_service

    def on_post(self, request: falcon.Request, response: falcon.Response):
        schema = WorkflowSchema()
        request_payload = request.media
        logger.info(f"Request to proceed: {request_payload}")
        result = schema.load(request_payload)

        if result.errors:
            logger.error(f"Invalid workflows response: {result.errors}")
            raise falcon.HTTPBadRequest(result.errors)

        workflow = result.data
        argo_workflow = create_argo_workflow(workflow)

        logger.info(f"Creating argo workflow in the kubernetes service.")
        output = self.kubernetes_service.create_argo_workflow(argo_workflow)
        logger.info(f"The argo workflow has been created successfully.")

        response.media = output["metadata"]
        response.status = falcon.HTTP_OK

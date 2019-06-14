import abc
import logging
from typing import Any
from typing import Dict

from kubernetes import client
from kubernetes import config
from kubernetes.config import ConfigException

logger = logging.getLogger()


class KubernetesServiceABC(abc.ABC):
    @abc.abstractmethod
    def create_argo_workflow(self, body=Dict[str, Any]):
        ...


class KubernetesService(KubernetesServiceABC):
    namespace = "argo"

    def __init__(self):
        self._load_config()
        self._cr_cli = client.CustomObjectsApi()

    def _load_config(self):
        try:
            config.load_incluster_config()
        except ConfigException as e:
            logger.error("Failed to load Kubernetes config in-cluster mode.")
            logger.info("Kubernetes config loaded in-cluster mode.")
        else:
            logger.info("Kubernetes config loaded in-cluster.")
            return

        try:
            config.load_kube_config()
        except ConfigException as e:
            logger.error("Failed to load Kubernetes config kube-config mode.")
            raise e
        else:
            logger.info("Kubernetes config loaded from kube-config file.")
            return

    def create_argo_workflow(self, body=Dict[str, Any]):
        return self._cr_cli.create_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=self.namespace,
            plural="workflows",
            body=body,
        )

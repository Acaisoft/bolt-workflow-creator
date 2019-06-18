import json
from unittest.mock import create_autospec

import falcon
import pytest
from falcon import testing
from falcon.testing import Result

from src.app import create_app
from src.services import KubernetesServiceABC


@pytest.fixture(scope="module")
def kubernetes_service():
    return create_autospec(KubernetesServiceABC)


@pytest.fixture
def cli(kubernetes_service):
    app = create_app(kubernetes_service)
    return testing.TestClient(app)


def test_create_workflow_1(cli, kubernetes_service):
    data = {
        "tenant_id": "world-corp",
        "project_id": "test-project",
        "repository_url": "git@exmaple.git/repo/123",
        "execution_id": "execution-identifier",
        "auth_token": "some_token",
        "duration_seconds": 123,
        "job_pre_start": {"env_vars": {"foo": "bar"}},
        "job_post_stop": {"env_vars": {"foo": "bar"}},
        "job_monitoring": {"env_vars": {"foo": "bar"}},
        "job_load_tests": {"env_vars": {"foo": "bar"}, "workers": 5},
        "no_cache": True,
    }

    response: Result = cli.simulate_post("/workflows", body=json.dumps(data).encode())

    kubernetes_service.create_argo_workflow.assert_called_once()
    assert response.status == falcon.HTTP_OK

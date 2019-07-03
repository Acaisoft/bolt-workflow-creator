from random import choice
from string import ascii_lowercase
from string import digits
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from src.dao import Workflow

# TODO: move to configuration file
GRAPHQL_URL = "http://hasura.hasura.svc.cluster.local/v1alpha1/graphql"


def create_argo_workflow(workflow: Workflow) -> Dict[str, Any]:
    """
    Returns argoproj.io/v1alpha1 Workflow as dict (in json format)
    """
    resource_definition = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "name": f"bolt-wf-{_postfix_generator()}",
            # TODO specify namespace via some external config
            "namespace": "argo",
        },
        "spec": {
            "entrypoint": "main",
            "templates": _generate_templates(workflow),
            "volumes": _generate_volumes(workflow),
            "serviceAccountName": "argo",
        },
    }
    if workflow.job_post_stop:
        resource_definition["spec"]["onExit"] = "post-stop"
    return resource_definition


def _generate_templates(workflow: Workflow):
    main_template = _generate_main_template(workflow)
    build_template = _generate_build_template(workflow)
    execution_template = _generate_execution_template(workflow)
    steps_templates = _generate_steps_templates(workflow)

    return [main_template, execution_template, build_template, *steps_templates]


def _generate_build_template(workflow: Workflow):
    no_cache_value = "1" if workflow.no_cache else "0"
    return {
        "name": "build",
        "container": {
            # TODO we should used tagged image, but for now pull always...
            "imagePullPolicy": "Always",
            "image": "eu.gcr.io/acai-bolt/argo-builder",
            "volumeMounts": [
                {"mountPath": "/root/.ssh", "name": "ssh"},
                {"mountPath": "/etc/kaniko", "name": "kaniko-secret"},
            ],
            "env": [
                {"name": "REPOSITORY_URL", "value": workflow.repository_url},
                {
                    "name": "GOOGLE_APPLICATION_CREDENTIALS",
                    "value": "/etc/kaniko/kaniko-secret.json",
                },
                {"name": "CLOUDSDK_CORE_PROJECT", "value": "acai-bolt"},
                {"name": "TENANT_ID", "value": workflow.tenant_id},
                {"name": "PROJECT_ID", "value": workflow.project_id},
                {
                    "name": "REDIS_URL",
                    # TODO pass redis password the other way
                    "value": "redis://:6a8ba845b1f74199be011e8bbdcdcec2@redis-master.redis.svc.cluster.local",
                },
                {"name": "NO_CACHE", "value": no_cache_value},
                {"name": "BOLT_EXECUTION_ID", "value": workflow.execution_id},
                {"name": "BOLT_GRAPHQL_URL", "value": GRAPHQL_URL},
                {"name": "BOLT_HASURA_TOKEN", "value": workflow.auth_token},
            ],
        },
        "outputs": {
            "parameters": [
                {
                    "globalName": "image",
                    "name": "image",
                    "valueFrom": {"path": "/tmp/image.txt"},
                }
            ]
        },
    }


def _generate_main_template(workflow: Workflow) -> Dict[str, Any]:
    return {
        "name": "main",
        "steps": [
            [{"name": "build", "template": "build"}],
            [{"name": "execution", "template": "execution"}],
        ],
    }


def _generate_execution_template(workflow: Workflow):
    tasks = []

    if workflow.job_pre_start:
        tasks.append({"name": "pre-start", "template": "pre-start"})

    if workflow.job_load_tests is not None:
        master_dependencies = []
        if workflow.job_pre_start is not None:
            master_dependencies.append("pre-start")

        tasks.append(
            {
                "name": "load-tests-master",
                "template": "load-tests-master",
                "dependencies": master_dependencies,
            }
        )

        for i in range(workflow.job_load_tests.workers):
            tasks.append(
                {
                    "name": f"load-tests-slave-{i + 1:03}",
                    "template": "load-tests-slave",
                    "dependencies": ["load-tests-master"],
                    "arguments": {
                        "parameters": [
                            {
                                "name": "master-ip",
                                "value": "{{tasks.load-tests-master.ip}}",
                            }
                        ]
                    },
                }
            )

    if workflow.job_monitoring is not None:
        monitor_dependencies = []
        if workflow.job_pre_start is not None:
            monitor_dependencies.append("pre-start")

        tasks.append(
            {
                "name": "monitoring",
                "template": "monitoring",
                "dependencies": monitor_dependencies,
            }
        )

    return {"name": "execution", "dag": {"tasks": tasks}}


def _generate_steps_templates(workflow) -> List[Dict[str, Any]]:
    templates = []

    if workflow.job_pre_start is not None:
        template_pre_start = {
            "name": "pre-start",
            "nodeSelector": {"group": "load-tests-workers-slave"},
            "container": {
                "image": "{{workflow.outputs.parameters.image}}",
                "command": ["python", "-m", "bolt_run", "pre_start"],
                "env": [
                    *_map_envs(workflow.job_pre_start.env_vars),
                    {"name": "BOLT_EXECUTION_ID", "value": workflow.execution_id},
                    {"name": "BOLT_GRAPHQL_URL", "value": GRAPHQL_URL},
                    {"name": "BOLT_HASURA_TOKEN", "value": workflow.auth_token},
                ],
                "resources": {
                    "limits": {"cpu": "110m", "memory": "220Mi"},
                    "requests": {"cpu": "100m", "memory": "200Mi"},
                },
            },
        }
        templates.append(template_pre_start)

    if workflow.job_post_stop is not None:
        template_post_stop = {
            "name": "post-stop",
            "nodeSelector": {"group": "load-tests-workers-slave"},
            "metadata": {"labels": {"prevent-bolt-termination": "true"}},
            "container": {
                "image": "{{workflow.outputs.parameters.image}}",
                "command": ["python", "-m", "bolt_run", "post_stop"],
                "env": [
                    *_map_envs(workflow.job_post_stop.env_vars),
                    {"name": "BOLT_EXECUTION_ID", "value": workflow.execution_id},
                    {"name": "BOLT_GRAPHQL_URL", "value": GRAPHQL_URL},
                    {"name": "BOLT_HASURA_TOKEN", "value": workflow.auth_token},
                ],
                "resources": {
                    "limits": {"cpu": "110m", "memory": "220Mi"},
                    "requests": {"cpu": "100m", "memory": "200Mi"},
                },
            },
        }
        templates.append(template_post_stop)

    if workflow.job_monitoring is not None:
        template_monitoring = {
            "name": "monitoring",
            "nodeSelector": {"group": "load-tests-workers-slave"},
            "retryStrategy": {"limit": 5},
            "container": {
                "image": "{{workflow.outputs.parameters.image}}",
                "command": ["python", "-m", "bolt_run", "monitoring"],
                "env": [
                    *_map_envs(workflow.job_monitoring.env_vars),
                    {"name": "BOLT_EXECUTION_ID", "value": workflow.execution_id},
                    {"name": "BOLT_GRAPHQL_URL", "value": GRAPHQL_URL},
                    {"name": "BOLT_HASURA_TOKEN", "value": workflow.auth_token},
                ],
                "resources": {
                    "limits": {"cpu": "110m", "memory": "220Mi"},
                    "requests": {"cpu": "100m", "memory": "200Mi"},
                },
            },
        }
        templates.append(template_monitoring)

    if workflow.job_load_tests is not None:
        template_load_tests_master = {
            "name": "load-tests-master",
            "daemon": True,
            "nodeSelector": {"group": "load-tests-workers-master"},
            "container": {
                "image": "{{workflow.outputs.parameters.image}}",
                "command": ["python", "-m", "bolt_run", "load_tests"],
                "env": [
                    *_map_envs(workflow.job_load_tests.env_vars),
                    {"name": "BOLT_EXECUTION_ID", "value": workflow.execution_id},
                    {"name": "BOLT_GRAPHQL_URL", "value": GRAPHQL_URL},
                    {"name": "BOLT_HASURA_TOKEN", "value": workflow.auth_token},
                    {"name": "BOLT_WORKER_TYPE", "value": "master"},
                ],
                "resources": {
                    "limits": {"cpu": "110m", "memory": "220Mi"},
                    "requests": {"cpu": "100m", "memory": "200Mi"},
                },
            },
        }
        templates.append(template_load_tests_master)

        template_load_tests_slave = {
            "name": "load-tests-slave",
            "inputs": {"parameters": [{"name": "master-ip"}]},
            "nodeSelector": {"group": "load-tests-workers-slave"},
            "retryStrategy": {"limit": 5},
            "container": {
                "image": "{{workflow.outputs.parameters.image}}",
                "command": ["python", "-m", "bolt_run", "load_tests"],
                "env": [
                    *_map_envs(workflow.job_load_tests.env_vars),
                    {"name": "BOLT_EXECUTION_ID", "value": workflow.execution_id},
                    {"name": "BOLT_GRAPHQL_URL", "value": GRAPHQL_URL},
                    {"name": "BOLT_HASURA_TOKEN", "value": workflow.auth_token},
                    {"name": "BOLT_WORKER_TYPE", "value": "slave"},
                    {
                        "name": "BOLT_MASTER_HOST",
                        "value": "{{inputs.parameters.master-ip}}",
                    },
                ],
                "resources": {
                    "limits": {"cpu": "440m", "memory": "550Mi"},
                    "requests": {"cpu": "400m", "memory": "500Mi"},
                },
            },
        }
        templates.append(template_load_tests_slave)

    return templates


def _generate_volumes(workflow: Workflow):
    return [
        {"name": "ssh", "secret": {"defaultMode": 384, "secretName": "ssh-files"}},
        {"name": "kaniko-secret", "secret": {"secretName": "kaniko-secret"}},
    ]


def _postfix_generator(num=6):
    return "".join(choice(ascii_lowercase + digits) for _ in range(num))


def _map_envs(env_vars: Optional[Dict[str, str]]) -> List[Dict]:
    if env_vars is None:
        return []

    output = []
    for key, value in env_vars.items():
        output.append({"name": key, "value": value})

    return output

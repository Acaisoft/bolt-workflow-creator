from random import choice
from string import ascii_lowercase
from string import digits
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from src import custom_logger
from src.dao import Workflow

# TODO: move to configuration file
GRAPHQL_URL = "http://hasura.hasura.svc.cluster.local/v1alpha1/graphql"
logger = custom_logger.setup_custom_logger(__file__)


def create_argo_workflow(workflow: Workflow) -> Dict[str, Any]:
    """
    Returns argoproj.io/v1alpha1 Workflow as dict (in json format)
    """
    pod_name = f"bolt-wf-{_postfix_generator()}"
    logger.info(f"Pod name: {pod_name}")

    resource_definition = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "name": pod_name,
            # TODO specify namespace via some external config
            "namespace": "argo",
        },
        "spec": {
            "entrypoint": "main",
            "templates": _generate_templates(workflow),
            "volumes": _generate_volumes(workflow),
            "serviceAccountName": "argo",
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": {
                            "matchExpressions": [
                                {
                                    "key": "nodel_pool",
                                    "operator": "In",
                                    "values": [
                                        "load-tests-workers-slaves",
                                        "load-tests-workers-masters",
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        },
    }
    if workflow.job_post_stop:
        resource_definition["spec"]["onExit"] = "post-stop"
    return resource_definition


def _generate_templates(workflow: Workflow):
    main_template = _generate_main_template(workflow)
    logger.info(f"The main template has been created.")
    build_template = _generate_build_template(workflow)
    logger.info(f"The bolt-builder template has been created.")
    execution_template = _generate_execution_template(workflow)
    logger.info(f"The execution template has been created.")
    steps_templates = _generate_steps_templates(workflow)
    logger.info(f"The execution steps templates have been created.")
    return [main_template, execution_template, build_template, *steps_templates]


def _generate_build_template(workflow: Workflow):
    no_cache_value = "1" if workflow.no_cache else "0"
    return {
        "name": "build",
        "container": {
            # TODO we should used tagged image, but for now pull always...
            "imagePullPolicy": "Always",
            "image": "eu.gcr.io/acai-bolt/argo-builder:revival-v4",
            "volumeMounts": [
                {"mountPath": "/root/.ssh", "name": "ssh"},
                {"mountPath": "/etc/google", "name": "google-secret"},
            ],
            "env": [
                {"name": "REPOSITORY_URL", "value": workflow.repository_url},
                {"name": "BRANCH", "value": workflow.branch},
                {
                    "name": "GOOGLE_APPLICATION_CREDENTIALS",
                    "value": "/etc/google/google-secret.json",
                },
                {"name": "CLOUDSDK_CORE_PROJECT", "value": "acai-bolt"},
                {"name": "TENANT_ID", "value": workflow.tenant_id},
                {"name": "PROJECT_ID", "value": workflow.project_id},
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
            "activeDeadlineSeconds": 600,
            "container": {
                "image": "{{workflow.outputs.parameters.image}}",
                "command": ["python", "-m", "bolt_run", "pre_start"],
                "env": [
                    *_map_envs(workflow.job_pre_start.env_vars),
                    {"name": "BOLT_EXECUTION_ID", "value": workflow.execution_id},
                    {"name": "BOLT_GRAPHQL_URL", "value": GRAPHQL_URL},
                    {"name": "BOLT_HASURA_TOKEN", "value": workflow.auth_token},
                    {"name": "BOLT_USERS", "value": str(workflow.job_load_tests.users)},
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
            "activeDeadlineSeconds": 600,
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
            "retryStrategy": {"limit": 10},
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
            "activeDeadlineSeconds": 30000,
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
                    "limits": {"cpu": "410m", "memory": "520Mi"},
                    "requests": {"cpu": "400m", "memory": "500Mi"},
                },
            },
        }
        templates.append(template_load_tests_master)

        template_load_tests_slave = {
            "name": "load-tests-slave",
            "inputs": {"parameters": [{"name": "master-ip"}]},
            "nodeSelector": {"group": "load-tests-workers-slave"},
            "retryStrategy": {"limit": 10},
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
                    {"name": "BOLT_USERS", "value": str(workflow.job_load_tests.users)},
                ],
                "resources": {
                    "limits": {"cpu": "840m", "memory": "950Mi"},
                    "requests": {"cpu": "800m", "memory": "900Mi"},
                },
            },
        }
        if workflow.job_load_tests.host is not None:
            template_load_tests_slave["container"]["env"].append(
                {"name": "BOLT_HOST", "value": workflow.job_load_tests.host}
            )
        if workflow.job_load_tests.port is not None:
            template_load_tests_slave["container"]["env"].append(
                {"name": "BOLT_PORT", "value": str(workflow.job_load_tests.port)}
            )
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

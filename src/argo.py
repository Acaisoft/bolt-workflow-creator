from random import choice
from string import ascii_lowercase
from string import digits
from typing import Any
from typing import Dict
from typing import List

from src.dao import Workflow


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
                {
                    "name": "GOOGLE_APPLICATION_CREDENTIALS",
                    "value": "/etc/kaniko/kaniko-secret.json",
                },
                {"name": "CLOUDSDK_CORE_PROJECT", "value": "acai-bolt"},
                {"name": "TENANT_ID", "value": workflow.tenant_id},
                {"name": "PROJECT_ID", "value": workflow.project_id},
                {
                    "name": "REPOSITORY_URL",
                    "value": "git@bitbucket.org:acaisoft/load-events.git",
                },
                {
                    "name": "REDIS_URL",
                    "value": "redis://redis-master.redis.svc.cluster.local",
                },
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
                }
            )

    if workflow.job_monitoring is not None:
        monitor_dependencies = []
        if workflow.job_pre_start is not None:
            monitor_dependencies.append("pre-start")

        # When we run monitoring with load tests
        # then monitoring is ran in daemon mode
        # load-tests master's ip will be passed to
        # monitoring so they can coordinate themselves
        if workflow.job_load_tests is not None:
            monitor_dependencies.append("load-tests-master")

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
            "container": {
                "image": "docker/whalesay",
                "command": ["cowsay"],
                "args": ["pre-start"],
            },
        }
        templates.append(template_pre_start)

    if workflow.job_post_stop is not None:
        template_post_stop = {
            "name": "post-stop",
            "container": {
                "image": "docker/whalesay",
                "command": ["cowsay"],
                "args": ["{{workflow.outputs.parameters.image}}"],
            },
        }
        templates.append(template_post_stop)

    if workflow.job_monitoring is not None:
        template_monitoring = {
            "name": "monitoring",
            "daemon": workflow.job_load_tests is not None,
            "container": {"image": "jroslaniec/tapp"},
        }
        templates.append(template_monitoring)

    if workflow.job_load_tests is not None:
        template_load_tests_master = {
            "name": "load-tests-master",
            "daemon": True,
            "container": {"image": "jroslaniec/tapp"},
        }
        templates.append(template_load_tests_master)

        template_load_tests_slave = {
            "name": "load-tests-slave",
            "container": {
                "image": "docker/whalesay",
                "command": ["cowsay"],
                "args": ["load-tests-slave"],
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

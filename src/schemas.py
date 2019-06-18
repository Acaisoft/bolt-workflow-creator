from marshmallow import Schema
from marshmallow import fields
from marshmallow import post_load

from src.dao import JobLoadTests
from src.dao import JobMonitoring
from src.dao import JobPostStop
from src.dao import JobPreStart
from src.dao import Workflow


class PreStartSchema(Schema):
    env_vars = fields.Dict()


class PostStopSchema(Schema):
    env_vars = fields.Dict()


class MonitoringSchema(Schema):
    env_vars = fields.Dict()


class LoadTestsSchema(Schema):
    env_vars = fields.Dict()
    workers = fields.Integer()


class WorkflowSchema(Schema):
    tenant_id = fields.Str(required=True)
    project_id = fields.Str(required=True)

    execution_id = fields.Str(required=True)
    auth_token = fields.Str(required=True)

    repository_url = fields.Str(required=True)

    duration_seconds = fields.Integer(required=True)

    job_pre_start = fields.Nested(PreStartSchema, missing=None)
    job_post_stop = fields.Nested(PostStopSchema, missing=None)
    job_monitoring = fields.Nested(MonitoringSchema, missing=None)
    job_load_tests = fields.Nested(LoadTestsSchema, missing=None)

    no_cache = fields.Boolean(required=False, missing=False)

    @post_load
    def make_workflow(self, data):
        data["job_pre_start"] = (
            JobPreStart(**data["job_pre_start"])
            if data["job_pre_start"] is not None
            else None
        )
        data["job_post_stop"] = (
            JobPostStop(**data["job_post_stop"])
            if data["job_post_stop"] is not None
            else None
        )
        data["job_monitoring"] = (
            JobMonitoring(**data["job_monitoring"])
            if data["job_monitoring"] is not None
            else None
        )
        data["job_load_tests"] = (
            JobLoadTests(**data["job_load_tests"])
            if data["job_load_tests"] is not None
            else None
        )
        return Workflow(**data)

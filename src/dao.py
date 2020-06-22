from dataclasses import dataclass
from typing import Dict
from typing import Optional


@dataclass
class JobPreStart:
    env_vars: Optional[Dict[str, str]] = None


@dataclass
class JobPostStop:
    env_vars: Optional[Dict[str, str]] = None


@dataclass
class JobMonitoring:
    env_vars: Optional[Dict[str, str]] = None


@dataclass
class JobLoadTests:
    workers: int
    users: int
    env_vars: Optional[Dict[str, str]] = None
    host: Optional[str] = None
    port: Optional[int] = None


@dataclass
class Workflow:
    tenant_id: str
    project_id: str

    repository_url: str
    branch: str

    execution_id: str
    auth_token: str

    duration_seconds: int

    job_pre_start: Optional[JobPreStart]
    job_post_stop: Optional[JobPostStop]
    job_monitoring: Optional[JobMonitoring]
    job_load_tests: Optional[JobLoadTests]

    no_cache: bool

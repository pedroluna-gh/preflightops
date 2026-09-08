"""Immutable GCP read scope. Construction performs no I/O or credential discovery."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from .evidence import canonical_json
from .provider_contract import ProviderContractError, _identifier

ResourceKind = Literal["policy", "dashboard", "uptime", "service", "slo"]
_PATHS = {
    "policy": r"alertPolicies/[A-Za-z0-9_-]{1,128}",
    "dashboard": r"dashboards/[A-Za-z0-9_-]{1,128}",
    "uptime": r"uptimeCheckConfigs/[A-Za-z0-9_-]{1,128}",
    "service": r"services/[A-Za-z0-9_-]{1,128}",
    "slo": r"services/[A-Za-z0-9_-]{1,128}/serviceLevelObjectives/[A-Za-z0-9_-]{1,128}",
}


def _project(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", value):
        raise ProviderContractError("Expected canonical project ID, not an organization or number.")


def _alias(value: str) -> None:
    _identifier(value)
    if len(value) > 48:
        raise ProviderContractError("GCP alias exceeds identity budget.")


@dataclass(frozen=True, slots=True)
class GcpResource:
    control_id: str
    kind: ResourceKind
    name: str = field(repr=False)

    def __post_init__(self) -> None:
        _alias(self.control_id)
        if not isinstance(self.kind, str) or self.kind not in _PATHS:
            raise ProviderContractError("Unsupported GCP resource capability.")
        if not isinstance(self.name, str) or not re.fullmatch(
            r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/" + _PATHS[self.kind], self.name
        ):
            raise ProviderContractError("Invalid explicitly selected GCP resource.")


@dataclass(frozen=True, slots=True)
class GcpMetric:
    control_id: str
    metric_type: str = field(repr=False)
    resource_type: str = field(repr=False)
    labels: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    max_sample_age: int = 300

    def __post_init__(self) -> None:
        _alias(self.control_id)
        if not isinstance(self.metric_type, str) or not re.fullmatch(
            r"[a-z][a-z0-9.]{0,127}/[A-Za-z0-9_/-]{1,256}", self.metric_type
        ):
            raise ProviderContractError("Invalid metric type.")
        if not isinstance(self.resource_type, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,127}", self.resource_type
        ):
            raise ProviderContractError("Invalid monitored resource type.")
        if type(self.max_sample_age) is not int or not 1 <= self.max_sample_age <= 86400:
            raise ProviderContractError("Invalid sample age budget.")
        if type(self.labels) is not tuple or len(self.labels) > 16:
            raise ProviderContractError("Expected bounded immutable metric labels.")
        keys = []
        for pair in self.labels:
            if type(pair) is not tuple or len(pair) != 2:
                raise ProviderContractError("Invalid metric label pair.")
            key, value = pair
            if (
                not isinstance(key, str)
                or not re.fullmatch(
                    r"(?:metric|resource)\.labels\.[a-zA-Z_][a-zA-Z0-9_]{0,63}", key
                )
                or key == "resource.labels.project_id"
                or not isinstance(value, str)
                or not 1 <= len(value) <= 256
                or any(ord(c) < 32 or ord(c) > 126 for c in value)
            ):
                raise ProviderContractError("Invalid or reserved metric label.")
            keys.append(key)
        if keys != sorted(set(keys)):
            raise ProviderContractError("Metric labels must be uniquely ordered.")

    def query_filter(self, project_id: str) -> str:
        """Only conjunctions of quoted literals; never accept an executable filter."""
        self.__post_init__()
        _project(project_id)
        pairs = (
            ("resource.labels.project_id", project_id),
            ("metric.type", self.metric_type),
            ("resource.type", self.resource_type),
            *self.labels,
        )
        return " AND ".join(key + " = " + json.dumps(value) for key, value in pairs)


@dataclass(frozen=True, slots=True)
class GcpAsset:
    control_id: str
    asset_type: str = field(repr=False)
    name: str = field(repr=False)

    def __post_init__(self) -> None:
        _alias(self.control_id)
        if not isinstance(self.asset_type, str) or not re.fullmatch(
            r"[a-z][a-z0-9]*\.googleapis\.com/[A-Za-z][A-Za-z0-9]{0,127}", self.asset_type
        ):
            raise ProviderContractError("Invalid explicit asset type.")
        if (
            not isinstance(self.name, str)
            or not re.fullmatch(
                r"//[a-z][a-z0-9]*\.googleapis\.com/projects/"
                r"[a-z][a-z0-9-]{4,28}[a-z0-9]/[A-Za-z0-9_/-]{1,512}",
                self.name,
            )
            or "//" in self.name[2:]
        ):
            raise ProviderContractError("Invalid explicit project asset name.")
        if self.name.split("/")[2] != self.asset_type.split("/")[0]:
            raise ProviderContractError("Asset service and type do not match.")


@dataclass(frozen=True, slots=True)
class GcpConfig:
    project_id: str = field(repr=False)
    allowed_projects: tuple[str, ...] = field(repr=False)
    project_reference: str
    principal_reference: str
    resources: tuple[GcpResource, ...] = field(default=(), repr=False)
    metrics: tuple[GcpMetric, ...] = field(default=(), repr=False)
    assets: tuple[GcpAsset, ...] = field(default=(), repr=False)
    ttl_seconds: int = 60
    lookback_seconds: int = 3600
    page_size: int = 100
    max_pages: int = 5
    max_response_bytes: int = 1_048_576
    retries: int = 2
    min_interval_ms: int = 100

    def __post_init__(self) -> None:
        _project(self.project_id)
        _alias(self.project_reference)
        _alias(self.principal_reference)
        if type(self.allowed_projects) is not tuple or not 1 <= len(self.allowed_projects) <= 20:
            raise ProviderContractError("Expected bounded immutable project allowlist.")
        for project in self.allowed_projects:
            _project(project)
        if self.allowed_projects != tuple(sorted(set(self.allowed_projects))):
            raise ProviderContractError("Project allowlist must be uniquely ordered.")
        if self.project_id not in self.allowed_projects:
            raise ProviderContractError("Project is outside the explicit allowlist.")
        identifiers = ["identity"]
        for selected, expected in (
            (self.resources, GcpResource),
            (self.metrics, GcpMetric),
            (self.assets, GcpAsset),
        ):
            if type(selected) is not tuple or len(selected) > 50:
                raise ProviderContractError("Expected bounded immutable GCP selection.")
            for item in selected:
                if type(item) is not expected:
                    raise ProviderContractError("Invalid GCP selection type.")
                item.__post_init__()
                identifiers.append(item.control_id)
                if isinstance(item, GcpResource) and not item.name.startswith(
                    "projects/" + self.project_id + "/"
                ):
                    raise ProviderContractError("Resource is outside the selected project.")
                if isinstance(item, GcpAsset) and item.name.split("/")[4] != self.project_id:
                    raise ProviderContractError("Asset is outside the selected project.")
        if len(identifiers) != len(set(identifiers)):
            raise ProviderContractError("GCP control identities must be unique.")
        for value, low, high in (
            (self.ttl_seconds, 1, 3600),
            (self.lookback_seconds, 1, 86400),
            (self.page_size, 1, 1000),
            (self.max_pages, 1, 20),
            (self.max_response_bytes, 256, 4_194_304),
            (self.retries, 0, 3),
            (self.min_interval_ms, 1, 10_000),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ProviderContractError("Invalid GCP execution budget.")
        if any(metric.max_sample_age > self.lookback_seconds for metric in self.metrics):
            raise ProviderContractError("Lookback must cover the configured sample age.")

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self))).hexdigest()

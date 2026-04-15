"""Configuration loading from YAML with env var interpolation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR} placeholders with environment variable values."""
    return re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.environ.get(m.group(1), m.group(0)),
        value,
    )


def _resolve_recursive(obj: object) -> object:
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _resolve_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_recursive(v) for v in obj]
    return obj


@dataclass
class AzureDevOpsConfig:
    organization: str
    pat: str
    projects: list[str]
    base_url: str = "https://dev.azure.com"


@dataclass
class ElasticsearchConfig:
    hosts: list[str]
    api_key: str
    datastream: str = "azure_devops.commit"


@dataclass
class PollingConfig:
    initial_lookback_days: int = 90


@dataclass
class Config:
    azure_devops: AzureDevOpsConfig
    elasticsearch: ElasticsearchConfig
    polling: PollingConfig = field(default_factory=PollingConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        raw = Path(path).read_text()
        data = _resolve_recursive(yaml.safe_load(raw))

        azdo = data["azure_devops"]
        es = data["elasticsearch"]
        polling = data.get("polling", {})

        return cls(
            azure_devops=AzureDevOpsConfig(
                organization=azdo["organization"],
                pat=azdo["pat"],
                projects=azdo["projects"],
                base_url=azdo.get("base_url", "https://dev.azure.com"),
            ),
            elasticsearch=ElasticsearchConfig(
                hosts=es["hosts"],
                api_key=es["api_key"],
                datastream=es.get("datastream", "azure_devops.commit"),
            ),
            polling=PollingConfig(
                initial_lookback_days=polling.get("initial_lookback_days", 90),
            ),
        )

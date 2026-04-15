"""Elasticsearch index template, ILM policy, and datastream setup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elasticsearch import Elasticsearch

logger = logging.getLogger(__name__)

CURSOR_INDEX = "azure-devops-commit-cursors"

ILM_POLICY_NAME = "azure-devops-commit-policy"

ILM_POLICY_BODY = {
    "policy": {
        "phases": {
            "hot": {
                "min_age": "0ms",
                "actions": {
                    "rollover": {
                        "max_primary_shard_size": "50gb",
                        "max_age": "30d",
                    },
                },
            },
            "warm": {
                "min_age": "30d",
                "actions": {
                    "shrink": {"number_of_shards": 1},
                    "forcemerge": {"max_num_segments": 1},
                },
            },
            "delete": {
                "min_age": "365d",
                "actions": {"delete": {}},
            },
        },
    },
}

INDEX_TEMPLATE_NAME = "azure_devops.commit"

INDEX_TEMPLATE_BODY = {
    "index_patterns": ["azure_devops.commit*"],
    "data_stream": {},
    "priority": 200,
    "template": {
        "settings": {
            "index.lifecycle.name": ILM_POLICY_NAME,
            "number_of_shards": 1,
            "number_of_replicas": 1,
        },
        "mappings": {
            "properties": {
                # --- ECS fields ---
                "@timestamp": {"type": "date"},
                "message": {"type": "text"},
                "event": {
                    "properties": {
                        "kind": {"type": "keyword"},
                        "category": {"type": "keyword"},
                        "type": {"type": "keyword"},
                        "action": {"type": "keyword"},
                        "module": {"type": "keyword"},
                        "dataset": {"type": "keyword"},
                    },
                },
                "user": {
                    "properties": {
                        "name": {"type": "keyword"},
                        "email": {"type": "keyword"},
                    },
                },
                # --- Custom fields (azure_devops namespace) ---
                "azure_devops": {
                    "properties": {
                        "organization": {"type": "keyword"},
                        "project": {
                            "properties": {
                                "id": {"type": "keyword"},
                                "name": {"type": "keyword"},
                            },
                        },
                        "repository": {
                            "properties": {
                                "id": {"type": "keyword"},
                                "name": {"type": "keyword"},
                            },
                        },
                        "commit": {
                            "properties": {
                                "id": {"type": "keyword"},
                                "url": {"type": "keyword"},
                                "committer": {
                                    "properties": {
                                        "name": {"type": "keyword"},
                                        "email": {"type": "keyword"},
                                        "date": {"type": "date"},
                                    },
                                },
                                "change_counts": {
                                    "properties": {
                                        "add": {"type": "integer"},
                                        "edit": {"type": "integer"},
                                        "delete": {"type": "integer"},
                                        "total": {"type": "integer"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}

CURSOR_INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
    },
    "mappings": {
        "properties": {
            "project": {"type": "keyword"},
            "repository_id": {"type": "keyword"},
            "repository_name": {"type": "keyword"},
            "last_commit_date": {"type": "date"},
            "updated_at": {"type": "date"},
        },
    },
}


def ensure_ilm_policy(es: Elasticsearch) -> None:
    if not es.ilm.get_lifecycle(name=ILM_POLICY_NAME, ignore=[404]).get(
        ILM_POLICY_NAME
    ):
        logger.info("Creating ILM policy %s", ILM_POLICY_NAME)
        es.ilm.put_lifecycle(name=ILM_POLICY_NAME, body=ILM_POLICY_BODY)
    else:
        logger.info("ILM policy %s already exists", ILM_POLICY_NAME)


def ensure_index_template(es: Elasticsearch) -> None:
    if not es.indices.exists_index_template(name=INDEX_TEMPLATE_NAME):
        logger.info("Creating index template %s", INDEX_TEMPLATE_NAME)
        es.indices.put_index_template(
            name=INDEX_TEMPLATE_NAME, body=INDEX_TEMPLATE_BODY
        )
    else:
        logger.info("Index template %s already exists", INDEX_TEMPLATE_NAME)


def ensure_datastream(es: Elasticsearch, name: str) -> None:
    if not es.indices.exists(index=name):
        logger.info("Creating datastream %s", name)
        es.indices.create_data_stream(name=name)
    else:
        logger.info("Datastream %s already exists", name)


def ensure_cursor_index(es: Elasticsearch) -> None:
    if not es.indices.exists(index=CURSOR_INDEX):
        logger.info("Creating cursor index %s", CURSOR_INDEX)
        es.indices.create(index=CURSOR_INDEX, body=CURSOR_INDEX_BODY)
    else:
        logger.info("Cursor index %s already exists", CURSOR_INDEX)


def setup_elasticsearch(es: Elasticsearch, datastream_name: str) -> None:
    """Create all required ES resources (idempotent)."""
    ensure_ilm_policy(es)
    ensure_index_template(es)
    ensure_datastream(es, datastream_name)
    ensure_cursor_index(es)

"""Gitastic — Azure DevOps commit ingestion into Elasticsearch datastreams."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from gitastic.azure_devops import AzureDevOpsClient
from gitastic.config import Config
from gitastic.es_setup import CURSOR_INDEX, setup_elasticsearch
from gitastic.transform import transform_commit

logger = logging.getLogger("gitastic")


# ---------------------------------------------------------------------------
# Cursor management
# ---------------------------------------------------------------------------


def get_cursor(es: Elasticsearch, project: str, repo_id: str) -> str | None:
    """Return the last_commit_date for a repo, or None if no cursor exists."""
    doc_id = f"{project}:{repo_id}"
    try:
        resp = es.get(index=CURSOR_INDEX, id=doc_id)
        return resp["_source"]["last_commit_date"]
    except Exception:
        return None


def update_cursor(
    es: Elasticsearch,
    project: str,
    repo_id: str,
    repo_name: str,
    last_commit_date: str,
) -> None:
    doc_id = f"{project}:{repo_id}"
    es.index(
        index=CURSOR_INDEX,
        id=doc_id,
        document={
            "project": project,
            "repository_id": repo_id,
            "repository_name": repo_name,
            "last_commit_date": last_commit_date,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Bulk indexing
# ---------------------------------------------------------------------------


def _bulk_actions(
    docs: list[dict[str, Any]],
    datastream: str,
) -> list[dict[str, Any]]:
    """Build bulk index actions using commitId as _id for idempotence."""
    actions = []
    for doc in docs:
        actions.append(
            {
                "_op_type": "create",
                "_index": datastream,
                "_id": doc["azure_devops"]["commit"]["id"],
                "_source": doc,
            }
        )
    return actions


# ---------------------------------------------------------------------------
# Per-repo ingestion
# ---------------------------------------------------------------------------


def ingest_repo(
    azdo: AzureDevOpsClient,
    es: Elasticsearch,
    config: Config,
    project_name: str,
    repo: dict[str, Any],
) -> int:
    """Ingest commits for a single repo. Returns number of indexed docs."""
    repo_id = repo["id"]
    repo_name = repo["name"]
    project_id = repo["project"]["id"]

    cursor = get_cursor(es, project_name, repo_id)
    if cursor is None:
        lookback = datetime.now(timezone.utc) - timedelta(
            days=config.polling.initial_lookback_days
        )
        from_date = lookback.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        from_date = cursor

    logger.info(
        "Fetching commits for %s/%s since %s", project_name, repo_name, from_date
    )
    commits = azdo.get_commits(project_name, repo_id, from_date=from_date)

    if not commits:
        logger.info("No new commits for %s/%s", project_name, repo_name)
        return 0

    docs = [
        transform_commit(
            c,
            organization=config.azure_devops.organization,
            project_id=project_id,
            project_name=project_name,
            repo_id=repo_id,
            repo_name=repo_name,
        )
        for c in commits
    ]

    actions = _bulk_actions(docs, config.elasticsearch.datastream)
    success, errors = bulk(es, actions, raise_on_error=False)

    if errors:
        logger.error(
            "Bulk indexing errors for %s/%s: %d failures",
            project_name,
            repo_name,
            len(errors),
        )
        for err in errors[:5]:
            logger.error("  %s", err)
        # Don't advance cursor on errors
        return success

    # Advance cursor to the most recent commit date
    newest_date = max(c["author"]["date"] for c in commits)
    update_cursor(es, project_name, repo_id, repo_name, newest_date)

    logger.info(
        "Indexed %d commits for %s/%s", success, project_name, repo_name
    )
    return success


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_es_client(config: Config) -> Elasticsearch:
    return Elasticsearch(
        hosts=config.elasticsearch.hosts,
        api_key=config.elasticsearch.api_key,
    )


def run(config: Config) -> None:
    es = build_es_client(config)
    azdo = AzureDevOpsClient(
        organization=config.azure_devops.organization,
        pat=config.azure_devops.pat,
        base_url=config.azure_devops.base_url,
    )

    logger.info("Setting up Elasticsearch resources...")
    setup_elasticsearch(es, config.elasticsearch.datastream)

    total = 0
    for project in config.azure_devops.projects:
        logger.info("Processing project: %s", project)
        try:
            repos = azdo.list_repositories(project)
        except Exception:
            logger.exception("Failed to list repos for project %s", project)
            continue

        for repo in repos:
            try:
                count = ingest_repo(azdo, es, config, project, repo)
                total += count
            except Exception:
                logger.exception(
                    "Failed to ingest repo %s/%s", project, repo.get("name", "?")
                )

    logger.info("Done. Total commits indexed: %d", total)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Azure DevOps commits into Elasticsearch"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Only create ES resources (index template, datastream, cursor index), then exit",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = Config.from_yaml(args.config)

    if args.setup_only:
        es = build_es_client(config)
        setup_elasticsearch(es, config.elasticsearch.datastream)
        logger.info("Elasticsearch setup complete.")
        sys.exit(0)

    run(config)


if __name__ == "__main__":
    main()

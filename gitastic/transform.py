"""Transform Azure DevOps API commit data into ECS-compliant documents."""

from __future__ import annotations

from typing import Any


def transform_commit(
    commit: dict[str, Any],
    *,
    organization: str,
    project_id: str,
    project_name: str,
    repo_id: str,
    repo_name: str,
) -> dict[str, Any]:
    """Map a raw Azure DevOps commit to an ECS-compliant ES document."""
    change_counts = commit.get("changeCounts", {})
    add = change_counts.get("Add", 0)
    edit = change_counts.get("Edit", 0)
    delete = change_counts.get("Delete", 0)

    comment = commit.get("comment", "")
    first_line = comment.split("\n", 1)[0][:256]

    return {
        # ECS fields
        "@timestamp": commit["author"]["date"],
        "message": first_line,
        "event": {
            "kind": "event",
            "category": ["configuration"],
            "type": ["change"],
            "action": "committed",
            "module": "azure_devops",
            "dataset": "azure_devops.commit",
        },
        "user": {
            "name": commit["author"]["name"],
            "email": commit["author"]["email"],
        },
        # Custom namespace
        "azure_devops": {
            "organization": organization,
            "project": {
                "id": project_id,
                "name": project_name,
            },
            "repository": {
                "id": repo_id,
                "name": repo_name,
            },
            "commit": {
                "id": commit["commitId"],
                "url": commit.get("remoteUrl", ""),
                "committer": {
                    "name": commit["committer"]["name"],
                    "email": commit["committer"]["email"],
                    "date": commit["committer"]["date"],
                },
                "change_counts": {
                    "add": add,
                    "edit": edit,
                    "delete": delete,
                    "total": add + edit + delete,
                },
            },
        },
    }

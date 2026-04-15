# Gitastic

Ingest Azure DevOps commit data into Elasticsearch datastreams for analyzing commit habits (file-level change size).

## How it works

Gitastic is a polling script that:

1. Lists repositories from configured Azure DevOps projects
2. Fetches commits since the last stored cursor (per repo)
3. Transforms them into ECS-compliant Elasticsearch documents
4. Bulk-indexes into an Elasticsearch datastream
5. Advances the cursor on successful indexation

## Prerequisites

- Python 3.12+
- An Azure DevOps PAT with read access to repositories
- An Elasticsearch 8.x cluster with an API key

## Installation

```bash
pip install -e .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install -e .
```

## Configuration

Copy the example config and edit it:

```bash
cp config.example.yaml config.yaml
```

```yaml
azure_devops:
  organization: "my-org"
  pat: "${AZDO_PAT}"
  # base_url: "https://azuredevops.my-company.com"  # for on-prem instances
  projects:
    - "ProjectA"
    - "ProjectB"

elasticsearch:
  hosts: ["https://es-cluster:9200"]
  api_key: "${ES_API_KEY}"
  datastream: "azure_devops.commit"

polling:
  initial_lookback_days: 90
```

Values wrapped in `${...}` are resolved from environment variables at runtime.

### On-premises Azure DevOps

For on-prem Azure DevOps Server instances, set `base_url` to your server URL:

```yaml
azure_devops:
  base_url: "https://azuredevops.my-company.com"
  organization: "DefaultCollection"
```

The default is `https://dev.azure.com` (Azure DevOps Services / cloud).

## Usage

### Set up Elasticsearch resources only

Creates the ILM policy, index template, datastream, and cursor index:

```bash
python -m gitastic.main --setup-only -c config.yaml
```

### Run the ingestion

```bash
export AZDO_PAT="your-personal-access-token"
export ES_API_KEY="your-elasticsearch-api-key"

python -m gitastic.main -c config.yaml
```

Add `-v` for verbose (debug) logging.

### Automate with systemd timer or cron

The script is designed to run periodically. Example crontab entry (every 15 minutes):

```cron
*/15 * * * * AZDO_PAT=... ES_API_KEY=... python -m gitastic.main -c /path/to/config.yaml
```

## Elasticsearch resources created

| Resource | Name | Purpose |
|---|---|---|
| ILM policy | `azure-devops-commit-policy` | hot/warm/delete lifecycle (rollover at 50GB or 30d, delete at 365d) |
| Index template | `azure_devops.commit` | Mapping with ECS fields + `azure_devops.*` custom namespace |
| Data stream | `azure_devops.commit` | Time-series storage for commit documents |
| Index | `azure-devops-commit-cursors` | Stores per-repo polling cursor (`last_commit_date`) |

## Document schema

Each commit is indexed as an ECS-compliant document with:

- **ECS fields**: `@timestamp`, `message`, `event.*`, `user.name`, `user.email`
- **Custom fields**: `azure_devops.organization`, `azure_devops.project.*`, `azure_devops.repository.*`, `azure_devops.commit.*`

The `change_counts` fields (`add`, `edit`, `delete`, `total`) represent the **number of files** changed, not lines.

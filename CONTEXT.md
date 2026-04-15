# Ingestion des commits Azure DevOps → Elasticsearch Datastream

## Objectif

Remonter les événements de commits depuis Azure DevOps vers un datastream Elasticsearch afin d'analyser les habitudes de commit (taille des changements au niveau fichier).

## Architecture retenue

Script Python de **polling périodique** (systemd timer / cron) qui :

1. Liste les repos des projets configurés via l'API REST Azure DevOps
2. Pour chaque repo, récupère les commits depuis le dernier curseur
3. Transforme les données en documents ECS-compliant
4. Indexe en bulk dans un datastream Elasticsearch
5. Met à jour le curseur stocké dans Elasticsearch

## Décisions techniques

| Sujet | Choix | Justification |
|---|---|---|
| Source des données | API REST Azure DevOps v7.1 | Centaines de repos, clone local non viable |
| Auth Azure DevOps | PAT (Personal Access Token) | Simple, suffisant pour du read-only |
| Granularité diff | File-level (`changeCounts`) | L'API ne fournit pas le line-level (Add/Edit/Delete = nombre de fichiers, pas de lignes) |
| Stockage curseur | Dans Elasticsearch | Pas de fichier local à maintenir, cursor par repo |
| Scope projets | Liste configurable | Pas tous les projets de l'org |
| Format documents | Convention ECS (Elastic Common Schema) | Standard, interopérable avec Kibana dashboards |

## Endpoints API Azure DevOps utilisés

### Lister les repositories d'un projet

```
GET https://dev.azure.com/{org}/{project}/_apis/git/repositories?api-version=7.1
```

### Récupérer les commits (inclut `changeCounts` directement)

```
GET https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repoId}/commits?searchCriteria.fromDate={cursor}&api-version=7.1
```

Réponse type :

```json
{
  "commitId": "9991b4f6...",
  "author": {
    "name": "Norman Paulk",
    "email": "norman@example.com",
    "date": "2018-06-15T17:06:53Z"
  },
  "committer": {
    "name": "Norman Paulk",
    "email": "norman@example.com",
    "date": "2018-06-15T17:06:53Z"
  },
  "comment": "Merged PR 2: Deleted README.md",
  "changeCounts": {
    "Add": 0,
    "Edit": 0,
    "Delete": 1
  }
}
```

### Note sur `changeCounts`

`changeCounts.Add`, `.Edit`, `.Delete` représentent le **nombre de fichiers** ajoutés/modifiés/supprimés, **PAS** le nombre de lignes. L'API REST Azure DevOps n'expose pas de compteur de lignes modifiées. L'UI Azure DevOps l'affiche mais utilise un endpoint interne (`HierarchyQuery` / `ms.vss-code-web.file-diff-data-provider`) qui nécessite un appel par fichier — non viable à l'échelle.

## Mapping ECS des documents Elasticsearch

### Champs ECS natifs

| Champ ECS | Source API | Type ES |
|---|---|---|
| `@timestamp` | `author.date` | `date` |
| `message` | `comment` (première ligne, tronqué) | `text` |
| `event.kind` | `"event"` (constante) | `keyword` |
| `event.category` | `["configuration"]` (constante) | `keyword` |
| `event.type` | `["change"]` (constante) | `keyword` |
| `event.action` | `"committed"` (constante) | `keyword` |
| `event.module` | `"azure_devops"` (constante) | `keyword` |
| `event.dataset` | `"azure_devops.commit"` (constante) | `keyword` |
| `user.name` | `author.name` | `keyword` |
| `user.email` | `author.email` | `keyword` |

### Champs custom (namespace `azure_devops`)

| Champ | Source API | Type ES |
|---|---|---|
| `azure_devops.commit.id` | `commitId` | `keyword` |
| `azure_devops.commit.url` | `remoteUrl` | `keyword` |
| `azure_devops.commit.committer.name` | `committer.name` | `keyword` |
| `azure_devops.commit.committer.email` | `committer.email` | `keyword` |
| `azure_devops.commit.committer.date` | `committer.date` | `date` |
| `azure_devops.commit.change_counts.add` | `changeCounts.Add` | `integer` |
| `azure_devops.commit.change_counts.edit` | `changeCounts.Edit` | `integer` |
| `azure_devops.commit.change_counts.delete` | `changeCounts.Delete` | `integer` |
| `azure_devops.commit.change_counts.total` | Somme calculée (add+edit+delete) | `integer` |
| `azure_devops.repository.id` | ID du repo | `keyword` |
| `azure_devops.repository.name` | Nom du repo | `keyword` |
| `azure_devops.project.id` | ID du projet | `keyword` |
| `azure_devops.project.name` | Nom du projet | `keyword` |
| `azure_devops.organization` | Nom de l'org (config) | `keyword` |

## Configuration attendue

Le script doit lire sa configuration depuis des variables d'environnement ou un fichier YAML :

```yaml
azure_devops:
  organization: "my-org"
  pat: "${AZDO_PAT}"           # via env var
  projects:
    - "ProjectA"
    - "ProjectB"
    - "ProjectC"

elasticsearch:
  hosts: ["https://es-cluster:9200"]
  api_key: "${ES_API_KEY}"     # via env var
  datastream: "azure_devops.commit"

polling:
  # Fréquence gérée par systemd timer, pas par le script
  initial_lookback_days: 90    # première exécution : remonter N jours
```

## Gestion du curseur dans Elasticsearch

Stocker un document par repo dans un index dédié (`azure-devops-commit-cursors`) :

```json
{
  "_id": "{project}:{repoId}",
  "project": "ProjectA",
  "repository_id": "abc-123",
  "repository_name": "my-repo",
  "last_commit_date": "2026-04-15T10:30:00Z",
  "updated_at": "2026-04-15T10:35:00Z"
}
```

## Points d'attention pour l'implémentation

- **Pagination** : l'API commits retourne max 100 résultats par défaut, utiliser `$top` et `$skip` pour paginer
- **Rate limiting** : Azure DevOps a un rate limit, prévoir un backoff exponentiel ou un délai entre repos
- **Datastream** : créer un index template + ILM policy + data stream `azure_devops.commit` avant la première indexation
- **Idempotence** : utiliser `commitId` comme `_id` du document pour éviter les doublons en cas de re-exécution
- **Erreurs** : logger proprement, ne pas avancer le curseur d'un repo si l'indexation a échoué

# Deploy to Azure

`azd up` provisions the Azure resources in [`infra/`](../infra/) and deploys the Python
Function App. It does not submit a policy request automatically.

## Prerequisites

- An [Azure subscription](https://azure.microsoft.com/free/)
- [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Python 3.13](https://www.python.org/downloads/)
- Permission to create resources and role assignments, such as Owner, or Contributor
  plus User Access Administrator, at the deployment scope

The selected region must support Azure Functions Flex Consumption, Durable Task
Scheduler, and the configured Microsoft Foundry model.

## Provision and deploy

Create the local Python environment:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Authenticate and deploy:

```bash
azd auth login
azd up
```

On the first run, `azd` prompts for an environment name, subscription, and region. The
deployment:

1. creates the resource group and Azure resources
2. creates the managed identity and scoped role assignments
3. configures the Function App with identity-based service connections
4. packages and deploys `src/`

`azd up` creates billable resources.

## What gets deployed

| Resource | Configuration |
|---|---|
| Function App | Flex Consumption, Python 3.13 |
| Durable Task Scheduler | Consumption by default, with a `policyreviews` task hub |
| Microsoft Foundry | Account, project, and `gpt-4.1` Global Standard deployment |
| Storage account | Request queue, report container, and Function deployment container |
| Managed identity | User-assigned identity attached to the Function App |
| Monitoring | Application Insights and Log Analytics |

Shared key access is disabled on the Storage account. The Function App uses managed
identity for host storage, the queue trigger, report publication, Microsoft Foundry,
Application Insights, and Durable Task Scheduler.

## Role assignments

| Principal | Scope and role | Purpose |
|---|---|---|
| Function identity | Storage Blob Data Owner | Function deployment storage, host Blob operations, and review packet publication |
| Function identity | Storage Queue Data Contributor | Read the policy servicing queue |
| Function identity | Storage Table Data Contributor | Functions host table operations on `AzureWebJobsStorage` |
| Function identity | Monitoring Metrics Publisher | Send identity-authenticated telemetry |
| Function identity | Cognitive Services User and Cognitive Services OpenAI User | Call the Foundry model |
| Function identity | Durable Task Data Contributor on the task hub | Schedule and run workflows |
| Deploying user | Storage Blob Data Contributor and Storage Queue Data Contributor | Submit requests and download reports with the demo |
| Deploying user | Foundry user roles and Durable Task Data Contributor | Use the deployed model and scheduler dashboard |

Role assignment propagation can take a few minutes after a new deployment.

## Deployment outputs

`azd` stores deployment outputs in the selected environment:

| Output | Use |
|---|---|
| `AZURE_FUNCTION_NAME` | Function App name |
| `AZURE_STORAGE_ACCOUNT_NAME` | Storage account name |
| `POLICY_REVIEW_QUEUE_URL` | Queue service endpoint used by the demo |
| `POLICY_REQUEST_QUEUE` | Request queue name |
| `POLICY_REVIEW_STORAGE_URL` | Blob service endpoint used by the app and demo |
| `POLICY_REVIEW_CONTAINER` | Report container name |
| `DURABLE_TASK_SCHEDULER_NAME` | Scheduler resource name |
| `DURABLE_TASK_HUB_NAME` | Task hub name |
| `DURABLE_TASK_DASHBOARD_URL` | Workflow dashboard |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint |
| `FOUNDRY_MODEL` | Model deployment name |

Inspect one output with `azd env get-value <name>`.

## Submit a cloud request

The demo uses `AzureDeveloperCliCredential`, so it reuses `azd auth login`. Export the
Storage outputs:

```bash
export POLICY_REVIEW_STORAGE_URL="$(azd env get-value POLICY_REVIEW_STORAGE_URL)"
export POLICY_REVIEW_QUEUE_URL="$(azd env get-value POLICY_REVIEW_QUEUE_URL)"
export POLICY_REVIEW_CONTAINER="$(azd env get-value POLICY_REVIEW_CONTAINER)"
export POLICY_REQUEST_QUEUE="$(azd env get-value POLICY_REQUEST_QUEUE)"
```

Submit the default request:

```bash
python scripts/demo.py submit
```

Open Application Insights Logs and the scheduler dashboard:

```bash
azd monitor --logs
azd env get-value DURABLE_TASK_DASHBOARD_URL
```

In Application Insights Logs, run:

```kusto
traces
| where message contains "POLICY_REVIEW_PACKET_PUBLISHED"
| order by timestamp desc
```

You can also use the scheduler dashboard and wait for
`publish_policy_review_packet` to complete. Then download the report:

```bash
python scripts/demo.py download
```

## Change the deployment model

The template defaults to `gpt-4.1` version `2025-04-14` with capacity 10. If that
deployment is unavailable in the selected region, configure an available model before
running `azd up`:

```bash
azd env set FOUNDRY_MODEL <deployment-name>
azd env set FOUNDRY_MODEL_NAME <model-name>
azd env set FOUNDRY_MODEL_VERSION <model-version>
azd env set FOUNDRY_DEPLOYMENT_CAPACITY <capacity>
```

The Bicep module currently uses the `GlobalStandard` deployment SKU.

## Use Durable Task Scheduler Dedicated

Consumption is the default. To provision Dedicated:

```bash
azd env set DTS_SKU_NAME Dedicated
azd env set DTS_DEDICATED_CAPACITY 1
azd up
```

## Clean up

```bash
azd down --purge
```

Next: [How it works](how-it-works.md) | [Use cases](use-cases.md) |
[Customize](customize.md) | [Troubleshooting](troubleshooting.md)

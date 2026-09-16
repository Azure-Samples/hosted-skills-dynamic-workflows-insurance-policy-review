# Deploy to Azure

## Prerequisites

- An Azure subscription
- Python 3.13
- Azure Developer CLI (`azd`)
- Permission to create resources and role assignments

The region must support Azure Functions Flex Consumption, Durable Task Scheduler, and
the configured Microsoft Foundry model.

## Deploy

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
azd auth login
azd up
```

The deployment creates:

- an Azure Functions app
- Durable Task Scheduler and a `policyreviews` task hub
- a Microsoft Foundry project and model deployment
- Storage for the request queue and HTML reports
- Application Insights and Log Analytics
- a managed identity and required role assignments

These resources can incur charges.

## Run the sample

Load the deployment outputs:

```bash
export POLICY_REVIEW_STORAGE_URL="$(azd env get-value POLICY_REVIEW_STORAGE_URL)"
export POLICY_REVIEW_QUEUE_URL="$(azd env get-value POLICY_REVIEW_QUEUE_URL)"
export POLICY_REVIEW_CONTAINER="$(azd env get-value POLICY_REVIEW_CONTAINER)"
export POLICY_REQUEST_QUEUE="$(azd env get-value POLICY_REQUEST_QUEUE)"
```

Submit the request and open the dashboard:

```bash
python scripts/demo.py submit
azd env get-value DURABLE_TASK_DASHBOARD_URL
```

After `publish_driver_review_report` completes:

```bash
python scripts/demo.py download
```

## Deployment outputs

| Output | Purpose |
|---|---|
| `POLICY_REVIEW_QUEUE_URL` | Queue service endpoint |
| `POLICY_REQUEST_QUEUE` | Request queue name |
| `POLICY_REVIEW_STORAGE_URL` | Blob service endpoint |
| `POLICY_REVIEW_CONTAINER` | Report container name |
| `DURABLE_TASK_DASHBOARD_URL` | Workflow dashboard |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint |
| `FOUNDRY_MODEL` | Model deployment name |

The app uses managed identity for Azure services. Shared key access is disabled in the
cloud deployment.

## Choose another model

Set model values before `azd up` when the default deployment is unavailable:

```bash
azd env set FOUNDRY_MODEL <deployment-name>
azd env set FOUNDRY_MODEL_NAME <model-name>
azd env set FOUNDRY_MODEL_VERSION <model-version>
azd env set FOUNDRY_DEPLOYMENT_CAPACITY <capacity>
```

## Clean up

```bash
azd down --purge
```

Next: [Troubleshoot](troubleshooting.md) | [How it works](how-it-works.md)

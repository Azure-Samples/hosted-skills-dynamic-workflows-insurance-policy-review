# Troubleshooting

## `azd up` cannot create role assignments

The deploying identity needs permission to create both resources and role assignments.
Use Owner, or Contributor plus User Access Administrator, at the target subscription or
resource group scope.

## The model deployment fails

The selected region might not support the configured model, version, SKU, or requested
capacity. Set an available deployment before running `azd up`:

```bash
azd env set FOUNDRY_MODEL <deployment-name>
azd env set FOUNDRY_MODEL_NAME <model-name>
azd env set FOUNDRY_MODEL_VERSION <model-version>
azd env set FOUNDRY_DEPLOYMENT_CAPACITY <capacity>
```

The current Bicep module uses `GlobalStandard`.

## The queue message is not processed

Open Application Insights Logs:

```bash
azd monitor --logs
```

Then query for recent host and workflow messages:

```kusto
traces
| order by timestamp desc
| take 100
```

Confirm that:

- the Function App deployed successfully
- `POLICY_REQUEST_QUEUE` resolves to `policy-service-requests`
- the Function identity has Storage Queue Data Contributor
- the queue message contains one JSON object
- the request has no more than eight document entries

New role assignments can take a few minutes to propagate.

## The workflow does not start

Inspect the Function App settings and the scheduler outputs:

```bash
azd env get-value DURABLE_TASK_SCHEDULER_NAME
azd env get-value DURABLE_TASK_HUB_NAME
azd env get-value DURABLE_TASK_DASHBOARD_URL
```

The app setting `TASKHUB_NAME` must match the created task hub, and
`DURABLE_TASK_SCHEDULER_CONNECTION_STRING` must use the scheduler endpoint and the
Function identity client ID. The Function identity also needs Durable Task Data
Contributor scoped to that task hub.

The hosted skill is instructed not to create a workflow when `body_json` is not an
object. A workflow that is created can still fail in its deterministic first activity
if required request fields are invalid.

## The report Blob is missing

The queue-triggered turn returns before the durable workflow finishes. Open the Durable
Task Scheduler dashboard and check every activity through
`publish_policy_review_packet`.

In the Function logs, look for:

```text
POLICY_REVIEW_PACKET_PUBLISHED
```

Confirm the Function identity has Storage Blob Data Owner and that
`POLICY_REVIEW_STORAGE_URL` and `POLICY_REVIEW_CONTAINER` match the deployment outputs.

## The cloud demo returns `403`

Run `azd auth login` again and confirm the four cloud Storage variables are exported in
the current terminal. The deploying user needs Storage Queue Data Contributor and
Storage Blob Data Contributor. Wait for role propagation after a fresh deployment,
then retry.

## A custom report cannot be downloaded

The default download targets `reviews/PSR-2026-00042.html`. Supply the Blob name and
local output path used by your request:

```bash
python scripts/demo.py download \
  --blob reviews/<request-id>.html \
  --output output/<request-id>.html
```

## Local Functions cannot import `azure_functions_agents`

Activate the repository virtual environment before starting Functions:

```bash
cd src
source ../.venv/bin/activate
func start
```

Starting `func` with a system Python that does not contain the dependencies results in
`ModuleNotFoundError`.

## Local Durable Task Scheduler connection fails

The sample expects the emulator on ports `8080` and `8082`, with a task hub named
`policyreviews`:

```bash
docker run --rm --name dts-emulator \
  -e DTS_TASK_HUB_NAMES=policyreviews \
  -p 8080:8080 -p 8082:8082 \
  mcr.microsoft.com/dts/dts-emulator:latest
```

Docker must be running. Open <http://localhost:8082> to confirm the dashboard is
available.

## Local Storage connection fails

Start Azurite and keep it running:

```bash
azurite --silent --skipApiVersionCheck --location .azurite
```

`src/local.settings.json` should keep
`"AzureWebJobsStorage": "UseDevelopmentStorage=true"`.

## Windows local development

Create and activate the environment from PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item src/local.settings.template.json src/local.settings.json
az login
```

Load the cloud demo outputs in PowerShell:

```powershell
$env:POLICY_REVIEW_STORAGE_URL = azd env get-value POLICY_REVIEW_STORAGE_URL
$env:POLICY_REVIEW_QUEUE_URL = azd env get-value POLICY_REVIEW_QUEUE_URL
$env:POLICY_REVIEW_CONTAINER = azd env get-value POLICY_REVIEW_CONTAINER
$env:POLICY_REQUEST_QUEUE = azd env get-value POLICY_REQUEST_QUEUE
```

Start the Functions host with the virtual environment active:

```powershell
Set-Location src
func start
```

## The report has no policy decision

That is expected. This sample prepares evidence only. Every report intentionally keeps
`review_status: human_review_required` and `decision: null`; an authorized human
reviewer owns the final decision.

Next: [How it works](how-it-works.md) | [Use cases](use-cases.md) |
[Customize](customize.md) | [Deploy](deploy.md)

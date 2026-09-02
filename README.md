# Dynamic Workflows insurance policy review

This standalone Azure Functions hosted skills sample turns an Azure Storage Queue
message into a durable policy servicing review workflow. It uses Dynamic Workflows,
currently available as public experimental v1, to collect policy context, inspect
submitted document metadata in parallel, build a review packet, render HTML, and
publish the packet to Azure Blob Storage.

The sample does not approve, deny, price, underwrite, or modify a policy. It prepares
evidence for a human policy reviewer, who remains responsible for the decision.

## Workflow shape

```text
Queue message
  |
  +-- validate request
        |
        +-- load policy context -------------------+
        |                                          |
        +-- inspect document 0 --+                  |
        +-- inspect document 1 --+-- ordered fan-in+-- build review packet
        +-- inspect document N --+                        |
                                                        render HTML
                                                            |
                                                        publish Blob
```

The hosted skill authors one validated task graph. The runtime schedules it as a
Durable Functions orchestration and returns a workflow ID without waiting for the
work to finish. Document checks run from a bounded source array with a maximum of
eight items. Unsupported document kinds are skipped, while the ordered fan-in keeps
their source positions visible.

All handlers under `src/tools/` are synchronous `@workflow_tool` functions. They
accept one dictionary and return JSON-serializable values. The final publisher
overwrites a stable Blob name, which makes repeated activity execution safe for this
sample.

## What is simulated

`load_policy_context` reads a small set of fictional policy fixtures.
`inspect_policy_document` evaluates only the metadata in the queue message. It does
not open files or verify authenticity. Replace these handlers with approved policy
and document systems before adapting the sample for production.

The following boundary remains enforced even if you replace the fixtures:

- Automation may gather evidence, identify missing information, and prepare the
  packet.
- A human reviewer must verify the source documents, apply current carrier rules,
  and record the final policy decision.

## Project layout

```text
.
|-- azure.yaml
|-- examples/policy-service-request.json
|-- infra/
|   |-- main.bicep
|   |-- main.parameters.json
|   `-- app/
|-- scripts/demo.py
|-- src/
|   |-- function_app.py
|   |-- host.json
|   |-- local.settings.template.json
|   |-- main.agent.md
|   `-- tools/policy_review_tools.py
`-- tests/
```

## Prerequisites

- Python 3.13
- Azure Functions Core Tools 4
- Docker (required for the Durable Task Scheduler emulator)
- Azurite, either through Docker or a local installation
- Azure CLI
- Azure Developer CLI (`azd`)
- A Microsoft Foundry project and deployed model

The sample pins `azurefunctions-agents-runtime` to the current beta used when this
project was created.

## Run locally

From this directory, create the environment:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp src/local.settings.template.json src/local.settings.json
```

Set `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` in
`src/local.settings.json`, then authenticate:

```bash
az login
```

Start the Durable Task Scheduler emulator:

```bash
docker run --rm --name dts-emulator \
  -e DTS_TASK_HUB_NAMES=policyreviews \
  -p 8080:8080 -p 8082:8082 \
  mcr.microsoft.com/dts/dts-emulator:latest
```

Instead of the emulator, you can point
`DURABLE_TASK_SCHEDULER_CONNECTION_STRING` at a provisioned Durable Task
Scheduler resource. The local emulator path documented here requires Docker.

Start Azurite in another terminal:

```bash
docker run --rm --name azurite \
  -p 10000:10000 -p 10001:10001 -p 10002:10002 \
  mcr.microsoft.com/azure-storage/azurite:latest \
  azurite --silent --skipApiVersionCheck \
  --blobHost 0.0.0.0 --queueHost 0.0.0.0 --tableHost 0.0.0.0
```

You can use a locally installed `azurite` command instead:

```bash
azurite --silent --skipApiVersionCheck
```

Start the Functions host from the app root with the virtual environment active:

```bash
cd src
func start
```

Submit the included request from a second terminal:

```bash
cd ~/workspace/dynamic-workflows-insurance-policy-review
source .venv/bin/activate
python scripts/demo.py submit
```

The request is sent to `policy-service-requests`. Watch the Functions logs for a
workflow start followed by `POLICY_REVIEW_PACKET_PUBLISHED`. Open the Durable Task
Scheduler dashboard at <http://localhost:8082> to inspect the orchestration and
activity results.

Download the generated review packet:

```bash
python scripts/demo.py download
```

The default file is written to `output/PSR-2026-00042.html`.

## Deploy to Azure

The included `azd` assets create a resource group containing:

- a Python 3.13 Flex Consumption Function App
- a user-assigned managed identity
- Azure Storage with the request queue, report container, and deployment container
- a Durable Task Scheduler and task hub
- a Microsoft Foundry project and `gpt-4.1` deployment
- Application Insights and Log Analytics
- the data-plane role assignments used by the app and the person running `azd`

The Function App uses managed identity for Azure Storage, Durable Task Scheduler,
Microsoft Foundry, and Application Insights. Storage access keys are not placed in app
settings.

Sign in, choose an environment, and provision the sample:

```bash
azd auth login
azd env new
azd up
```

`azd up` creates billable Azure resources. The signed-in account needs permission to
create the resources and role assignments, such as Owner or User Access Administrator
plus Contributor at the target subscription or resource group scope. The selected
region must support Flex Consumption, Durable Task Scheduler, and the configured model
deployment. If `gpt-4.1` is unavailable there, set an available deployment before
running `azd up`:

```bash
azd env set FOUNDRY_MODEL <deployment-name>
azd env set FOUNDRY_MODEL_NAME <model-name>
azd env set FOUNDRY_MODEL_VERSION <model-version>
```

The default Durable Task Scheduler SKU is Consumption. To use Dedicated instead:

```bash
azd env set DTS_SKU_NAME Dedicated
azd env set DTS_DEDICATED_CAPACITY 1
```

After deployment, load the Storage outputs into a terminal that still has the Python
environment active:

```bash
export POLICY_REVIEW_STORAGE_URL="$(azd env get-value POLICY_REVIEW_STORAGE_URL)"
export POLICY_REVIEW_QUEUE_URL="$(azd env get-value POLICY_REVIEW_QUEUE_URL)"
export POLICY_REVIEW_CONTAINER="$(azd env get-value POLICY_REVIEW_CONTAINER)"
export POLICY_REQUEST_QUEUE="$(azd env get-value POLICY_REQUEST_QUEUE)"
```

The demo uses `AzureDeveloperCliCredential`, so it reuses the identity from
`azd auth login`. Submit the example queue message:

```bash
python scripts/demo.py submit
```

Use the scheduler dashboard URL to follow the durable workflow:

```bash
azd env get-value DURABLE_TASK_DASHBOARD_URL
```

When the Functions logs contain `POLICY_REVIEW_PACKET_PUBLISHED`, download the stable
Blob:

```bash
python scripts/demo.py download
```

Delete the Azure resources when you are finished:

```bash
azd down --purge
```

## Example request

The complete payload is in `examples/policy-service-request.json`:

```json
{
  "request_id": "PSR-2026-00042",
  "policy_id": "AUTO-100042",
  "requested_change": {
    "type": "add_driver",
    "effective_date": "2026-09-15",
    "details": {
      "driver_name": "Jordan Lee",
      "driver_license_last4": "4831"
    }
  },
  "documents": [
    {
      "document_id": "DOC-001",
      "kind": "driver_license",
      "file_name": "jordan-lee-license.pdf",
      "status": "received"
    }
  ],
  "review_blob": "reviews/PSR-2026-00042.html"
}
```

The full example includes supported, missing, and out-of-scope documents so the
workflow demonstrates parallel inspection, a constrained skip, and ordered fan-in.
The validator also accepts an empty document list, allowing the workflow to publish a
packet that identifies all required evidence as missing.

The model carries request fields from the queue message into the authored workflow
plan. A reviewer should compare those fields with the authoritative source request,
in addition to verifying the source documents.

## Test

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest
ruff check .
```

## References

- <https://azure.github.io/azure-functions-agents-runtime/workflows/>
- <https://github.com/Azure/azure-functions-agents-runtime/tree/main/samples/workflow-queue-p0-report>
- <https://learn.microsoft.com/azure/azure-functions/durable/>

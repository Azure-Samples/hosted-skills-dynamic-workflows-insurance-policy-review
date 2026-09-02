from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


def test_complete_azd_asset_set_exists() -> None:
    expected = {
        ROOT / "azure.yaml",
        INFRA / "main.bicep",
        INFRA / "main.parameters.json",
        INFRA / "app" / "api.bicep",
        INFRA / "app" / "dts.bicep",
        INFRA / "app" / "foundry.bicep",
        INFRA / "app" / "rbac.bicep",
        INFRA / "app" / "storage.bicep",
    }

    assert {path for path in expected if path.is_file()} == expected


def test_azure_yaml_deploys_src_as_a_python_function() -> None:
    azure_yaml = (ROOT / "azure.yaml").read_text(encoding="utf-8")

    assert "project: ./src" in azure_yaml
    assert "language: python" in azure_yaml
    assert "host: function" in azure_yaml


def test_main_bicep_wires_required_services_and_outputs() -> None:
    main = (INFRA / "main.bicep").read_text(encoding="utf-8")

    for module in ("api.bicep", "dts.bicep", "foundry.bicep", "rbac.bicep", "storage.bicep"):
        assert module in main
    for setting in (
        "DURABLE_TASK_SCHEDULER_CONNECTION_STRING",
        "TASKHUB_NAME",
        "POLICY_REVIEW_STORAGE_URL",
        "POLICY_REVIEW_CONTAINER",
    ):
        assert setting in main
    for output in (
        "AZURE_FUNCTION_NAME",
        "AZURE_STORAGE_ACCOUNT_NAME",
        "DURABLE_TASK_DASHBOARD_URL",
        "FOUNDRY_PROJECT_ENDPOINT",
    ):
        assert f"output {output} " in main


def test_dts_module_uses_task_hub_scoped_managed_identity_rbac() -> None:
    dts = (INFRA / "app" / "dts.bicep").read_text(encoding="utf-8")

    assert "Microsoft.DurableTask/schedulers@2025-11-01" in dts
    assert "Microsoft.DurableTask/schedulers/taskHubs@2025-11-01" in dts
    assert "0ad04412-c4d5-4796-b79c-f76d14c8d402" in dts
    assert "scope: taskHub" in dts
    assert "taskHub.properties.dashboardUrl" in dts


def test_cloud_resources_disable_local_authentication() -> None:
    storage = (INFRA / "app" / "storage.bicep").read_text(encoding="utf-8")
    foundry = (INFRA / "app" / "foundry.bicep").read_text(encoding="utf-8")

    assert "allowSharedKeyAccess: false" in storage
    assert "disableLocalAuth: true" in foundry


def test_storage_module_creates_queue_and_report_container() -> None:
    storage = (INFRA / "app" / "storage.bicep").read_text(encoding="utf-8")

    assert "Microsoft.Storage/storageAccounts/queueServices/queues" in storage
    assert "requestQueueName" in storage
    assert "reportContainerName" in storage
    assert "deploymentContainerName" in storage


def test_parameters_cover_model_and_scheduler_choices() -> None:
    parameters = json.loads((INFRA / "main.parameters.json").read_text(encoding="utf-8"))[
        "parameters"
    ]

    assert parameters["environmentName"]["value"] == "${AZURE_ENV_NAME}"
    assert parameters["location"]["value"] == "${AZURE_LOCATION}"
    assert parameters["foundryModelName"]["value"]
    assert parameters["foundryModelVersion"]["value"]
    assert parameters["dtsSkuName"]["value"] == "${DTS_SKU_NAME=Consumption}"

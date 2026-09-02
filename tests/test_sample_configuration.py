from __future__ import annotations

import json
from pathlib import Path

import azure.durable_functions as df
from azure_functions_agents.app import create_function_app
from azure_functions_agents.config.loader import load_agent_specs
from azure_functions_agents.discovery.tools import (
    clear_tool_discovery_cache,
    discover_project_tools,
)
from azure_functions_agents.workflows.schema import validate_plan

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def test_agent_declares_queue_trigger_and_dynamic_workflows() -> None:
    [spec] = load_agent_specs(SRC)

    assert spec.is_main is True
    assert spec.trigger is not None
    assert spec.trigger.type == "queue_trigger"
    assert spec.trigger.args == {
        "queue_name": "policy-service-requests",
        "connection": "AzureWebJobsStorage",
    }
    assert spec.workflows is not None
    assert spec.workflows.enabled is True
    assert "create exactly one dynamic workflow" in spec.instructions.lower()
    assert "human reviewer" in spec.instructions


def test_host_uses_durable_task_scheduler_backend() -> None:
    host = json.loads((SRC / "host.json").read_text(encoding="utf-8"))

    assert host["extensions"]["durableTask"] == {
        "hubName": "%TASKHUB_NAME%",
        "storageProvider": {
            "type": "azureManaged",
            "connectionStringName": "DURABLE_TASK_SCHEDULER_CONNECTION_STRING",
        },
    }
    assert host["extensionBundle"]["version"] == "[4.32.0, 5.0.0)"


def test_local_settings_name_the_emulator_task_hub() -> None:
    settings = json.loads((SRC / "local.settings.template.json").read_text(encoding="utf-8"))

    assert settings["Values"]["TASKHUB_NAME"] == "policyreviews"


def test_app_indexes_queue_and_workflow_functions() -> None:
    app = create_function_app(app_root=SRC)

    assert isinstance(app, df.DFApp)
    functions = {
        builder._function._name: [
            binding.get_dict_repr() for binding in builder._function._bindings
        ]
        for builder in app._function_builders
    }
    assert {
        "agents_workflow_run_tool",
        "agents_workflow_orchestrator",
        "handler_Policy_Service_Review_Coordinator",
    } <= functions.keys()
    bindings = functions["handler_Policy_Service_Review_Coordinator"]
    assert [binding["type"] for binding in bindings] == [
        "durableClient",
        "queueTrigger",
    ]
    assert bindings[1]["queueName"] == "policy-service-requests"


def test_representative_dynamic_workflow_plan_validates() -> None:
    request = json.loads(
        (ROOT / "examples" / "policy-service-request.json").read_text(encoding="utf-8")
    )
    clear_tool_discovery_cache()
    workflow_tools = discover_project_tools(SRC).workflow_tools
    allowed_tools = {tool.name for tool in workflow_tools}

    assert allowed_tools == {
        "build_policy_review_packet",
        "inspect_policy_document",
        "load_policy_context",
        "publish_policy_review_packet",
        "render_policy_review_html",
        "validate_policy_service_request",
    }

    plan = validate_plan(
        {
            "tasks": [
                {
                    "id": "validate_request",
                    "type": "tool",
                    "tool": "validate_policy_service_request",
                    "args": {"request": request},
                },
                {
                    "id": "load_policy",
                    "type": "tool",
                    "tool": "load_policy_context",
                    "depends_on": ["validate_request"],
                    "args": {
                        "policy_id": "${validate_request.result.policy_id}",
                        "requested_change_type": (
                            "${validate_request.result.requested_change.type}"
                        ),
                    },
                },
                {
                    "id": "inspect_documents",
                    "type": "tool",
                    "tool": "inspect_policy_document",
                    "depends_on": ["validate_request"],
                    "for_each": "${validate_request.result.documents}",
                    "when": {
                        "ref": "${item.in_scope}",
                        "operator": "equals",
                        "value": True,
                    },
                    "args": {
                        "request_id": "${validate_request.result.request_id}",
                        "document": "${item}",
                        "position": "${index}",
                    },
                },
                {
                    "id": "build_packet",
                    "type": "tool",
                    "tool": "build_policy_review_packet",
                    "depends_on": ["load_policy", "inspect_documents"],
                    "args": {
                        "request": "${validate_request.result}",
                        "policy": "${load_policy.result}",
                        "document_checks": "${inspect_documents.result}",
                    },
                },
                {
                    "id": "render_html",
                    "type": "tool",
                    "tool": "render_policy_review_html",
                    "depends_on": ["build_packet"],
                    "args": {"packet": "${build_packet.result}"},
                },
                {
                    "id": "publish_packet",
                    "type": "tool",
                    "tool": "publish_policy_review_packet",
                    "depends_on": ["render_html"],
                    "args": {
                        "report": "${render_html.result}",
                        "blob_name": "${validate_request.result.review_blob}",
                    },
                },
            ]
        },
        allowed_tools=allowed_tools,
    )

    assert len(plan.tasks) == 6
    assert plan.tasks[2].for_each == "${validate_request.result.documents}"


def test_readme_does_not_assign_dynamic_workflows_a_separate_maturity_label() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "public experimental v1" not in readme
    assert "Dynamic Workflows preview" not in readme
    assert "Docker (required for the Durable Task Scheduler emulator)" in readme


def test_function_app_contains_deployable_requirements() -> None:
    root_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    app_requirements = (SRC / "requirements.txt").read_text(encoding="utf-8")

    assert app_requirements == root_requirements

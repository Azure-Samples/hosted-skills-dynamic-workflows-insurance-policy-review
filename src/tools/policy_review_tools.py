"""Deterministic workflow tools for a human-owned policy servicing review."""

from __future__ import annotations

import copy
import html
import json
import logging
import os
import re
from contextlib import suppress
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure_functions_agents import workflow_tool

logger = logging.getLogger(__name__)

_MAX_DOCUMENTS = 8
_DEFAULT_CONTAINER = "policy-review-packets"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_DOCUMENT_STATES = {"received", "missing", "expired"}

_DOCUMENT_REVIEW_GUIDANCE: dict[str, list[str]] = {
    "driver_license": [
        "Verify the license belongs to the requested driver.",
        "Confirm expiration date, issuing jurisdiction, and license class.",
    ],
    "signed_request": [
        "Confirm the signer is authorized to request the policy change.",
        "Compare the signature and effective date with the source request.",
    ],
    "proof_of_residency": [
        "Confirm the document date and address meet current carrier rules.",
        "Compare the address with the policy and requested change.",
    ],
    "vehicle_registration": [
        "Confirm the registered owner and vehicle identifiers.",
        "Compare the registration with the requested vehicle change.",
    ],
}

_POLICIES: dict[str, dict[str, Any]] = {
    "AUTO-100042": {
        "policy_id": "AUTO-100042",
        "line_of_business": "personal_auto",
        "status": "active",
        "named_insured": "Taylor Morgan",
        "term": {
            "effective_date": "2026-01-01",
            "expiration_date": "2027-01-01",
        },
        "covered_items": ["2022 Contoso Sedan"],
        "listed_drivers": ["Taylor Morgan"],
    },
    "HOME-200017": {
        "policy_id": "HOME-200017",
        "line_of_business": "homeowners",
        "status": "active",
        "named_insured": "Alex Chen",
        "term": {
            "effective_date": "2026-04-01",
            "expiration_date": "2027-04-01",
        },
        "covered_items": ["Fictional primary residence"],
        "listed_drivers": [],
    },
}

_CHANGE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "add_driver": {
        "required_documents": ["driver_license", "signed_request"],
        "optional_documents": ["proof_of_residency"],
        "review_notes": [
            "Confirm the requested driver and effective date.",
            "Apply the current driver eligibility and rating rules manually.",
        ],
    },
    "change_address": {
        "required_documents": ["signed_request", "proof_of_residency"],
        "optional_documents": [],
        "review_notes": [
            "Confirm the old and new addresses.",
            "Apply the current territory and policy servicing rules manually.",
        ],
    },
    "add_vehicle": {
        "required_documents": ["vehicle_registration", "signed_request"],
        "optional_documents": [],
        "review_notes": [
            "Confirm vehicle ownership and identifiers.",
            "Apply the current coverage and rating rules manually.",
        ],
    },
}


def _require_mapping(args: dict[str, Any], name: str) -> dict[str, Any]:
    value = args.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_identifier(value: Any, name: str) -> str:
    identifier = _require_string(value, name)
    if not _IDENTIFIER.fullmatch(identifier):
        raise ValueError(
            f"{name} must start with a letter or number and contain only "
            "letters, numbers, periods, underscores, or hyphens"
        )
    return identifier


def _normalize_blob_name(value: Any, request_id: str) -> str:
    if value is None:
        return f"reviews/{request_id}.html"
    blob_name = _require_string(value, "review_blob")
    if blob_name.startswith("/") or ".." in blob_name.split("/") or not blob_name.endswith(".html"):
        raise ValueError(
            "review_blob must be a relative Blob name ending in .html without '..' segments"
        )
    return blob_name


@workflow_tool(
    description=(
        "Validate and normalize one policy servicing queue request. Args: "
        "{request: <complete body_json object>}. The request needs request_id, "
        "policy_id, requested_change, and 0-8 documents. Returns "
        "{request_id, policy_id, requested_change, documents, review_blob}. "
        "Each returned document includes in_scope: bool. Use the returned "
        "documents array as the bounded source for a per-document workflow task."
    )
)
def validate_policy_service_request(args: dict[str, Any]) -> dict[str, Any]:
    request = _require_mapping(args, "request")
    request_id = _require_identifier(request.get("request_id"), "request_id")
    policy_id = _require_identifier(request.get("policy_id"), "policy_id")

    requested_change = request.get("requested_change")
    if not isinstance(requested_change, dict):
        raise ValueError("requested_change must be an object")
    change_type = _require_string(requested_change.get("type"), "requested_change.type")
    effective_date = _require_string(
        requested_change.get("effective_date"),
        "requested_change.effective_date",
    )
    details = requested_change.get("details", {})
    if not isinstance(details, dict):
        raise ValueError("requested_change.details must be an object")

    documents = request.get("documents")
    if not isinstance(documents, list):
        raise ValueError("documents must be a list")
    if len(documents) > _MAX_DOCUMENTS:
        raise ValueError(f"documents may contain at most {_MAX_DOCUMENTS} documents")

    normalized_documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for position, value in enumerate(documents):
        if not isinstance(value, dict):
            raise ValueError(f"documents[{position}] must be an object")
        document_id = _require_identifier(
            value.get("document_id"),
            f"documents[{position}].document_id",
        )
        if document_id in seen_ids:
            raise ValueError(f"duplicate document_id: {document_id}")
        seen_ids.add(document_id)

        kind = _require_string(value.get("kind"), f"documents[{position}].kind")
        file_name = _require_string(
            value.get("file_name"),
            f"documents[{position}].file_name",
        )
        status = _require_string(value.get("status"), f"documents[{position}].status")
        if status not in _DOCUMENT_STATES:
            allowed = ", ".join(sorted(_DOCUMENT_STATES))
            raise ValueError(f"documents[{position}].status must be one of: {allowed}")

        normalized_documents.append(
            {
                "document_id": document_id,
                "kind": kind,
                "file_name": file_name,
                "status": status,
                "in_scope": kind in _DOCUMENT_REVIEW_GUIDANCE,
            }
        )

    return {
        "request_id": request_id,
        "policy_id": policy_id,
        "requested_change": {
            "type": change_type,
            "effective_date": effective_date,
            "details": copy.deepcopy(details),
        },
        "documents": normalized_documents,
        "review_blob": _normalize_blob_name(request.get("review_blob"), request_id),
    }


@workflow_tool(
    description=(
        "Load deterministic fictional policy context for human servicing review. "
        "Args: {policy_id: str, requested_change_type: str}. Returns "
        "{found, policy, review_requirements}. It does not evaluate eligibility "
        "or make a policy decision."
    )
)
def load_policy_context(args: dict[str, Any]) -> dict[str, Any]:
    policy_id = _require_identifier(args.get("policy_id"), "policy_id")
    change_type = _require_string(
        args.get("requested_change_type"),
        "requested_change_type",
    )
    policy = _POLICIES.get(policy_id)
    requirements = _CHANGE_REQUIREMENTS.get(change_type)
    change_type_recognized = requirements is not None
    if requirements is None:
        requirements = {
            "required_documents": ["signed_request"],
            "optional_documents": [],
            "review_notes": [
                "Apply the current carrier rules for this servicing request manually."
            ],
        }
    return {
        "found": policy is not None,
        "requested_change_type": change_type,
        "change_type_recognized": change_type_recognized,
        "policy": copy.deepcopy(policy),
        "review_requirements": copy.deepcopy(requirements),
    }


@workflow_tool(
    description=(
        "Inspect one normalized in-scope document metadata record. Args: "
        "{request_id: str, document: <one normalized document>, position?: int}. "
        "Intended for bounded for_each over the validation result's documents, "
        "with a strict when check that ${item.in_scope} equals true. Returns "
        "{request_id, position, document_id, kind, file_name, evidence_state, "
        "observations, manual_checks, requires_manual_verification}. "
        "It does not verify file contents or make a decision."
    )
)
def inspect_policy_document(args: dict[str, Any]) -> dict[str, Any]:
    request_id = _require_identifier(args.get("request_id"), "request_id")
    document = _require_mapping(args, "document")
    if document.get("in_scope") is not True:
        raise ValueError("document must be an in-scope normalized document")

    document_id = _require_identifier(document.get("document_id"), "document.document_id")
    kind = _require_string(document.get("kind"), "document.kind")
    file_name = _require_string(document.get("file_name"), "document.file_name")
    status = _require_string(document.get("status"), "document.status")
    if kind not in _DOCUMENT_REVIEW_GUIDANCE:
        raise ValueError(f"unsupported in-scope document kind: {kind}")
    if status not in _DOCUMENT_STATES:
        raise ValueError(f"unsupported document status: {status}")

    raw_position = args.get("position", 0)
    if not isinstance(raw_position, int) or isinstance(raw_position, bool) or raw_position < 0:
        raise ValueError("position must be a non-negative integer")

    if status == "received":
        evidence_state = "present"
        observations = [
            f"{kind} metadata is present for {file_name}.",
            "File contents and authenticity have not been verified by this sample.",
        ]
    elif status == "missing":
        evidence_state = "missing"
        observations = [
            f"{kind} is marked missing in the servicing request.",
            "A human reviewer should request or locate the source document.",
        ]
    else:
        evidence_state = "needs_follow_up"
        observations = [
            f"{kind} is marked expired in the servicing request.",
            "A human reviewer should request a current source document.",
        ]

    return {
        "request_id": request_id,
        "position": raw_position,
        "document_id": document_id,
        "kind": kind,
        "file_name": file_name,
        "evidence_state": evidence_state,
        "observations": observations,
        "manual_checks": copy.deepcopy(_DOCUMENT_REVIEW_GUIDANCE[kind]),
        "requires_manual_verification": True,
    }


def _ordered_document_results(value: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list):
        raise ValueError("document_checks must be the complete ordered for_each aggregate")

    inspected: list[dict[str, Any]] = []
    skipped = 0
    for position, envelope in enumerate(value):
        if not isinstance(envelope, dict):
            raise ValueError(f"document_checks[{position}] must be an envelope")
        if envelope.get("index") != position:
            raise ValueError("document_checks must preserve source-index order")
        status = envelope.get("status")
        result = envelope.get("result")
        if status == "skipped":
            if result is not None:
                raise ValueError("a skipped document check must have a null result")
            skipped += 1
            continue
        if status != "completed" or not isinstance(result, dict):
            raise ValueError(
                "each document check must be completed with an object result or skipped"
            )
        normalized_result = copy.deepcopy(result)
        normalized_result["position"] = position
        inspected.append(normalized_result)
    return inspected, skipped


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


@workflow_tool(
    description=(
        "Build one decision-neutral human review packet. Args: "
        "{request: <whole validation result>, policy: <whole policy result>, "
        "document_checks: <whole source-ordered for_each aggregate>}. Returns "
        "a JSON-serializable packet with evidence, missing information, manual "
        "checks, next actions, review_status='human_review_required', and decision=null."
    )
)
def build_policy_review_packet(args: dict[str, Any]) -> dict[str, Any]:
    request = _require_mapping(args, "request")
    policy_result = _require_mapping(args, "policy")
    inspected, skipped = _ordered_document_results(args.get("document_checks"))

    request_id = _require_identifier(request.get("request_id"), "request.request_id")
    policy_id = _require_identifier(request.get("policy_id"), "request.policy_id")
    requested_change = _require_mapping(request, "requested_change")
    documents = request.get("documents")
    if not isinstance(documents, list):
        raise ValueError("request.documents must be a list")

    requirements = policy_result.get("review_requirements")
    if not isinstance(requirements, dict):
        raise ValueError("policy.review_requirements must be an object")
    required_documents = requirements.get("required_documents")
    if not isinstance(required_documents, list) or not all(
        isinstance(kind, str) for kind in required_documents
    ):
        raise ValueError("policy.review_requirements.required_documents must be a string list")

    present_kinds = {
        str(result.get("kind")) for result in inspected if result.get("evidence_state") == "present"
    }
    missing_information: list[str] = []
    if policy_result.get("found") is not True:
        missing_information.append(
            f"Policy context was not found for {policy_id}; locate the authoritative record."
        )
    if policy_result.get("change_type_recognized") is False:
        change_type = policy_result.get("requested_change_type")
        missing_information.append(
            f"Requested change type '{change_type}' is not covered by this sample's "
            "requirement fixtures; confirm the authoritative requirement list."
        )
    for kind in required_documents:
        if kind not in present_kinds:
            missing_information.append(f"Required evidence is not ready: {kind}.")
    for result in inspected:
        kind = str(result.get("kind"))
        state = result.get("evidence_state")
        if state != "present":
            document_id = result.get("document_id")
            missing_information.append(
                f"Evidence needs follow-up: {kind} ({document_id}) is {state}."
            )

    manual_checks = [
        check
        for result in inspected
        for check in result.get("manual_checks", [])
        if isinstance(check, str)
    ]
    review_notes = requirements.get("review_notes")
    if isinstance(review_notes, list):
        manual_checks.extend(note for note in review_notes if isinstance(note, str))
    manual_checks.extend(
        [
            "Verify every source document in the approved document system.",
            "Compare request fields in this packet with the authoritative source request.",
            "Confirm the policyholder is authorized to request the change.",
            "Record the human reviewer's final decision in the policy system.",
        ]
    )

    next_actions = []
    if missing_information:
        next_actions.append("Resolve each missing or follow-up item before a policy decision.")
    next_actions.extend(
        [
            "Review the packet against current carrier rules and authoritative records.",
            "Have an authorized human reviewer record the final decision and rationale.",
        ]
    )

    excluded_documents = [
        {
            "document_id": document.get("document_id"),
            "kind": document.get("kind"),
            "reason": "not included in this sample's bounded review scope",
        }
        for document in documents
        if isinstance(document, dict) and document.get("in_scope") is False
    ]
    present = sum(result.get("evidence_state") == "present" for result in inspected)

    return {
        "request_id": request_id,
        "review_status": "human_review_required",
        "decision": None,
        "decision_authority": "human_policy_reviewer",
        "automation_scope": "evidence_collection_and_packet_preparation_only",
        "request_summary": {
            "policy_id": policy_id,
            "requested_change": copy.deepcopy(requested_change),
            "review_blob": request.get("review_blob"),
        },
        "policy_summary": copy.deepcopy(policy_result.get("policy")),
        "review_requirements": copy.deepcopy(requirements),
        "document_summary": {
            "submitted": len(documents),
            "inspected": len(inspected),
            "skipped": skipped,
            "present": present,
            "missing_or_follow_up": len(inspected) - present,
        },
        "document_checks": copy.deepcopy(inspected),
        "excluded_documents": excluded_documents,
        "missing_information": _deduplicate(missing_information),
        "manual_checks": _deduplicate(manual_checks),
        "next_actions": next_actions,
        "disclaimer": (
            "Prepared by automation for human review. Request fields were carried into "
            "the workflow plan by the model and must be checked against the source system. "
            "No policy decision has been made."
        ),
    }


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _list_markup(values: Any, empty_text: str) -> str:
    if not isinstance(values, list) or not values:
        return f'<p class="empty">{_escape(empty_text)}</p>'
    return "<ul>" + "".join(f"<li>{_escape(value)}</li>" for value in values) + "</ul>"


@workflow_tool(
    description=(
        "Render a complete policy review packet as HTML. Args: "
        "{packet: <whole build_policy_review_packet result>}. Returns "
        "{html, request_id, review_status, decision}. Do not modify the packet's "
        "human-owned decision boundary."
    )
)
def render_policy_review_html(args: dict[str, Any]) -> dict[str, Any]:
    packet = _require_mapping(args, "packet")
    request_id = _require_identifier(packet.get("request_id"), "packet.request_id")
    if packet.get("review_status") != "human_review_required" or packet.get("decision") is not None:
        raise ValueError("packet must retain the human-review decision boundary")

    request_summary = packet.get("request_summary")
    policy_summary = packet.get("policy_summary")
    document_checks = packet.get("document_checks")
    if not isinstance(request_summary, dict):
        raise ValueError("packet.request_summary must be an object")
    if policy_summary is not None and not isinstance(policy_summary, dict):
        raise ValueError("packet.policy_summary must be an object or null")
    if not isinstance(document_checks, list):
        raise ValueError("packet.document_checks must be a list")

    change = request_summary.get("requested_change")
    change = change if isinstance(change, dict) else {}
    policy = policy_summary or {}
    rows = "".join(
        "<tr>"
        f"<td>{_escape(check.get('position', ''))}</td>"
        f"<td>{_escape(check.get('document_id', ''))}</td>"
        f"<td>{_escape(check.get('kind', ''))}</td>"
        f"<td>{_escape(check.get('evidence_state', ''))}</td>"
        f"<td>{_escape(check.get('file_name', ''))}</td>"
        "</tr>"
        for check in document_checks
        if isinstance(check, dict)
    )
    document_table = (
        "<table><thead><tr><th>Index</th><th>Document</th><th>Kind</th>"
        "<th>Evidence state</th><th>File</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if rows
        else '<p class="empty">No in-scope documents were inspected.</p>'
    )

    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Policy review {_escape(request_id)}</title>"
        "<style>"
        ":root{color-scheme:light;--ink:#172033;--muted:#5d687c;--line:#dfe5ef;"
        "--surface:#fff;--canvas:#f5f7fb;--accent:#185abd;--warn:#8a4b08;"
        "--warnbg:#fff4ce}*{box-sizing:border-box}body{margin:0;background:var(--canvas);"
        "color:var(--ink);font:15px/1.5 Segoe UI,system-ui,sans-serif}"
        "header{background:#14213d;color:#fff;padding:36px 24px}header div,main{max-width:"
        "1040px;margin:auto}h1{margin:0;font-size:32px}.subtitle{margin:8px 0 0;color:#d8e2f5}"
        "main{padding:24px}.notice{margin-bottom:20px;padding:16px 18px;border:1px solid "
        "#f0c36a;border-radius:10px;background:var(--warnbg);color:var(--warn)}"
        ".grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}"
        ".card{padding:20px;border:1px solid var(--line);border-radius:12px;"
        "background:var(--surface)}.wide{grid-column:1/-1}h2{margin:0 0 12px;font-size:19px}"
        "dl{display:grid;grid-template-columns:max-content 1fr;gap:7px 14px;margin:0}"
        "dt{color:var(--muted);font-weight:650}dd{margin:0}table{width:100%;border-collapse:"
        "collapse}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left;"
        "vertical-align:top}th{color:var(--muted);font-size:12px;text-transform:uppercase}"
        "ul{margin:0;padding-left:20px}.empty{margin:0;color:var(--muted)}"
        "footer{max-width:1040px;margin:auto;padding:0 24px 32px;color:var(--muted);"
        "font-size:12px}@media(max-width:720px){.grid{grid-template-columns:1fr}"
        ".wide{grid-column:auto}table{display:block;overflow-x:auto}}</style></head><body>"
        "<header><div><h1>Policy servicing review packet</h1>"
        f'<p class="subtitle">Request {_escape(request_id)}</p></div></header>'
        '<main><section class="notice"><strong>Human review required.</strong> '
        "No policy decision has been made. Verify source documents and current carrier "
        'rules before recording a decision.</section><div class="grid">'
        '<section class="card"><h2>Request</h2><dl>'
        f"<dt>Policy</dt><dd>{_escape(request_summary.get('policy_id', ''))}</dd>"
        f"<dt>Change</dt><dd>{_escape(change.get('type', ''))}</dd>"
        f"<dt>Effective date</dt><dd>{_escape(change.get('effective_date', ''))}</dd>"
        '</dl></section><section class="card"><h2>Policy context</h2><dl>'
        f"<dt>Named insured</dt><dd>{_escape(policy.get('named_insured', 'Not found'))}</dd>"
        f"<dt>Line</dt><dd>{_escape(policy.get('line_of_business', 'Not found'))}</dd>"
        f"<dt>Status</dt><dd>{_escape(policy.get('status', 'Not found'))}</dd>"
        '</dl></section><section class="card wide"><h2>Document evidence</h2>'
        f"{document_table}</section>"
        '<section class="card"><h2>Missing information</h2>'
        f"{_list_markup(packet.get('missing_information'), 'No missing items identified.')}"
        '</section><section class="card"><h2>Next actions</h2>'
        f"{_list_markup(packet.get('next_actions'), 'No next actions were generated.')}"
        '</section><section class="card wide"><h2>Manual checks</h2>'
        f"{_list_markup(packet.get('manual_checks'), 'No manual checks were generated.')}"
        "</section></div></main><footer>Fictional sample data. Request fields must be "
        "verified against the source system. Evidence preparation only. An authorized "
        "human reviewer owns the policy decision.</footer></body></html>"
    )
    return {
        "html": document,
        "request_id": request_id,
        "review_status": packet["review_status"],
        "decision": packet["decision"],
    }


@workflow_tool(
    description=(
        "Publish rendered review HTML to Azure Blob Storage as the terminal sink. "
        "Args: {report: <whole render_policy_review_html result>, blob_name: str}. "
        "Uses AzureWebJobsStorage and POLICY_REVIEW_CONTAINER. The stable destination "
        "is overwritten so repeated activity execution is safe. Returns Blob metadata."
    )
)
def publish_policy_review_packet(args: dict[str, Any]) -> dict[str, Any]:
    report = _require_mapping(args, "report")
    html_document = _require_string(report.get("html"), "report.html")
    request_id = _require_identifier(report.get("request_id"), "report.request_id")
    if report.get("review_status") != "human_review_required" or report.get("decision") is not None:
        raise ValueError("report must retain the human-review decision boundary")
    blob_name = _normalize_blob_name(args.get("blob_name"), request_id)

    container_name = os.environ.get("POLICY_REVIEW_CONTAINER", _DEFAULT_CONTAINER)

    connection_string = os.environ.get("AzureWebJobsStorage")  # noqa: SIM112
    storage_url = os.environ.get("POLICY_REVIEW_STORAGE_URL")
    if connection_string:
        service = BlobServiceClient.from_connection_string(connection_string)
    elif storage_url:
        credential = DefaultAzureCredential(
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID")
        )
        service = BlobServiceClient(account_url=storage_url, credential=credential)
    else:
        raise ValueError(
            "Configure AzureWebJobsStorage locally or POLICY_REVIEW_STORAGE_URL in Azure"
        )
    container = service.get_container_client(container_name)
    with suppress(ResourceExistsError):
        container.create_container()
    blob = container.get_blob_client(blob_name)
    blob.upload_blob(
        html_document.encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="text/html; charset=utf-8"),
    )

    result = {
        "event": "policy_review_packet_published",
        "container": container_name,
        "blob_name": blob_name,
        "request_id": request_id,
        "review_status": report["review_status"],
        "decision": report["decision"],
    }
    logger.warning("POLICY_REVIEW_PACKET_PUBLISHED %s", json.dumps(result))
    return result


__all__ = [
    "build_policy_review_packet",
    "inspect_policy_document",
    "load_policy_context",
    "publish_policy_review_packet",
    "render_policy_review_html",
    "validate_policy_service_request",
]

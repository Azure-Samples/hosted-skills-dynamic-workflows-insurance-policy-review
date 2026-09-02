# Use cases

The sample focuses on policy servicing evidence preparation. It does not automate
policy decisions. Each scenario ends with an HTML packet for an authorized human
reviewer.

## Included add-driver request

[`examples/policy-service-request.json`](../examples/policy-service-request.json)
requests an additional driver on the fictional `AUTO-100042` policy.

| Source index | Document kind | Input state | Workflow result |
|---|---|---|---|
| 0 | `driver_license` | `received` | Inspected, evidence present |
| 1 | `signed_request` | `received` | Inspected, evidence present |
| 2 | `proof_of_residency` | `missing` | Inspected, follow-up recorded |
| 3 | `customer_note` | `received` | Skipped because it is out of scope |

The ordered aggregate retains all four positions. The generated packet records the
missing optional evidence and manual verification steps, then leaves the policy
decision empty.

```bash
python scripts/demo.py submit
python scripts/demo.py download
```

## Supported request variations

The fictional fixtures cover three change types:

| Change type | Policy example | Required evidence |
|---|---|---|
| `add_driver` | `AUTO-100042` | Driver license and signed request |
| `add_vehicle` | `AUTO-100042` | Vehicle registration and signed request |
| `change_address` | `AUTO-100042` or `HOME-200017` | Signed request and proof of residency |

To try another request, copy the included JSON, change its `request_id`,
`requested_change`, `documents`, and `review_blob`, then submit the new file:

```bash
python scripts/demo.py submit --request examples/<request-file>.json
python scripts/demo.py download \
  --blob reviews/<request-id>.html \
  --output output/<request-id>.html
```

Document states can be `received`, `missing`, or `expired`. A missing document becomes
missing evidence. An expired document becomes a follow-up item.

## No submitted documents

An empty `documents` array is valid. The workflow still loads the applicable
requirements and publishes a packet that lists every required evidence type as
missing. This is useful when the servicing request arrives before supporting documents.

```json
{
  "request_id": "PSR-2026-00043",
  "policy_id": "HOME-200017",
  "requested_change": {
    "type": "change_address",
    "effective_date": "2026-10-01",
    "details": {
      "new_address": "100 Fictional Avenue"
    }
  },
  "documents": [],
  "review_blob": "reviews/PSR-2026-00043.html"
}
```

## Unknown policy or change type

The workflow can still prepare a packet when a policy fixture is not found or a change
type is not represented in the sample. The packet calls out the missing authoritative
context and requires the reviewer to confirm the correct evidence list and carrier
rules.

This behavior keeps the result useful without inventing policy data or treating an
unsupported request as approved.

## Malformed request

The hosted skill is instructed to report a validation error instead of starting a
workflow when the queue payload is not a JSON object. Once a workflow is started, the
deterministic first activity validates the request shape and fails explicitly on
invalid identifiers, duplicate document IDs, unsupported states, more than eight
documents, or an unsafe Blob name.

Next: [How it works](how-it-works.md) | [Customize](customize.md) |
[Deploy](deploy.md) | [Troubleshooting](troubleshooting.md)

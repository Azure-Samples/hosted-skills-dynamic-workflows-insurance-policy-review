# Try variations

The included request asks to add Jordan Lee to policy `AUTO-100042`.

| Document | Input status | Report result |
|---|---|---|
| Driver's license | `received` | `present` |
| Signed request | `missing` | `missing` |

Run it with:

```bash
python scripts/demo.py submit
python scripts/demo.py download
```

## Change a document status

Copy [the example request](../examples/policy-service-request.json), give it a new
`request_id` and `review_blob`, then set a document status to:

- `received`: the metadata is present
- `missing`: the reviewer must obtain the document
- `expired`: the reviewer must obtain a current copy

Submit the copy:

```bash
python scripts/demo.py submit --request examples/my-request.json
```

Download its report:

```bash
python scripts/demo.py download \
  --blob reviews/<request-id>.html \
  --output output/<request-id>.html
```

## Submit no documents

An empty `documents` list is valid. The report lists both required documents as missing.
This demonstrates that the workflow can still complete when its parallel step has no
items.

Next: [How it works](how-it-works.md) | [Customize](customize.md) |
[Deploy](deploy.md)

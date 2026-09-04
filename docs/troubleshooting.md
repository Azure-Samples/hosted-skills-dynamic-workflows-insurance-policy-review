# Troubleshooting

## The queue message is not processed

Run `azd monitor --logs` and confirm:

- the Function App deployed successfully
- `POLICY_REQUEST_QUEUE` is `policy-service-requests`
- the Function identity has Storage Queue Data Contributor
- the request matches the included JSON example

New role assignments can take a few minutes to propagate.

## The workflow does not start

Open the dashboard URL returned by:

```bash
azd env get-value DURABLE_TASK_DASHBOARD_URL
```

Check that the app's `TASKHUB_NAME` matches the deployed task hub and that the Function
identity has Durable Task Data Contributor on that task hub.

## The report is missing

The queue trigger returns before the workflow finishes. In the dashboard, wait for
`publish_driver_review_report`.

Also confirm `POLICY_REVIEW_STORAGE_URL` and `POLICY_REVIEW_CONTAINER` match the
`azd` outputs.

## The demo returns 403

Run `azd auth login` again and reload the four Storage environment variables shown in
the deployment guide. Role assignments can take a few minutes to become effective.

## A custom report cannot be downloaded

Pass the Blob path used in the request:

```bash
python scripts/demo.py download \
  --blob reviews/<request-id>.html \
  --output output/<request-id>.html
```

## Local imports fail

Activate the repository environment before starting Functions:

```bash
cd src
source ../.venv/bin/activate
func start
```

## The local scheduler cannot connect

Start Docker and run the emulator with the expected task hub:

```bash
docker run --rm --name dts-emulator \
  -e DTS_TASK_HUB_NAMES=policyreviews \
  -p 8080:8080 -p 8082:8082 \
  mcr.microsoft.com/dts/dts-emulator:latest
```

The dashboard is at <http://localhost:8082>.

## The report has no decision

That is expected. The sample prepares document metadata for review. An authorized
person must verify the actual documents and decide whether to update the policy.

Next: [Deploy](deploy.md) | [How it works](how-it-works.md)

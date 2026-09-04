---
name: Add Driver Review
description: Prepares an add-driver document review for an insurance representative.
workflows:
  enabled: true
trigger:
  type: queue_trigger
  args:
    queue_name: policy-service-requests
    connection: AzureWebJobsStorage
---

Process the request in `body_json` in four steps:

1. Validate the add-driver request.
2. Inspect every document in the validated request in parallel.
3. After all inspections finish, build one HTML review from the whole validated
   request and the complete ordered inspection result.
4. Publish the HTML to the validated Blob name.

Use each upstream result directly. Do not copy fields into the plan, invent
documents, add steps, or make a policy decision. The final report must require an
authorized person to verify the documents and decide whether to update the policy.

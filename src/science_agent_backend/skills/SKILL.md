---
name: icicle-services
description: Inspect files uploaded to Science Agent and query Smart Labeler pipelines, model cards, and job status from the remote pod.
---

# ICICLE Services In The Agent Pod

The web request supplies an absolute context file and tool script path. Use those
paths exactly. Credentials are in the private context file; never read it aloud,
print it, copy it into chat, or use another conversation's context.

Run the tool through the terminal, for example:

```sh
python3 <tool_path> --context <context_path> inspect-files
python3 <tool_path> --context <context_path> get /pipes
python3 <tool_path> --context <context_path> get /patra/list
python3 <tool_path> --context <context_path> get /pipe/2
python3 <tool_path> --context <context_path> arraymorph-health
```

Always inspect uploaded files when a request refers to them. File names, byte
counts, hashes, and image dimensions are not visual understanding. To describe
image content, use an available image-reading tool on the supplied remote path;
if unavailable, say you could inspect the file but could not view its contents.

Use actual tool results to list pipelines/models or report job status. An HTTP
error is a failure at that operation, not evidence that all services are down.
Do not infer model availability from names in this document. For recommendations:
BioCLIP is a candidate for plant/animal semantics, OWLv2 for open-vocabulary
animal detection, DINOv3 for general visual features, and SAM3 for proposals;
check available model cards and the user's task before choosing.

icicle_services.py implements read-only calls and file inspection. For requested
storage or labeling, read arraymorph/SKILL.md and use labeling/pod_workflow.py
--context PATH store or label. The label operation performs real ArrayMorph
storage and verified recovery before Tapis staging, pipeline creation and job
submission. Use status --job-id UUID for follow-up checks, never rerun label.
The current labeling flow submits object detection for one image, not a generic
segmentation or full classification workflow. Explain that distinction.
Use actual observations; submission is not completed computation.
For output inspection use labeling/pod_workflow.py --context PATH results
--job-id UUID --output-dir OBSERVED_OUTPUT_DIRECTORY. Report job status and actual
returned files separately. Empty listings and queued jobs are not labeling results.
API documentation is in references/api.md. Never substitute example paths.

ArrayMorph runs inside this pod using the isolated native environment described
in arraymorph/SKILL.md. No separate ArrayMorph HTTP service is needed for store or
label. Do not call arraymorph-health to decide whether those operations work.
On failure, report the last verified stage and the failing operation. HTTP 500
on a write does not prove that the write had no side effects. Inspect existing
records before retrying; never recreate a pipeline just to check job status.

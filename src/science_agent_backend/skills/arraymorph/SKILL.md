---
name: science-agent-arraymorph
description: Set up ArrayMorph inside the agent pod and plan array storage in ICICLE S3.
---

# Science Agent ArrayMorph

Read references/install.md before setup. Uploaded files are already available at
the request manifest paths; do not ask the user to upload them again.

For a user-requested upload, use the supplied store_files.py --context PATH
command. The private context contains this authenticated account's S3 profile
loaded from PostgreSQL. Never cat the context, echo its values, or use a global
credential file. This is the user's selected DB credential; never fall back to
local AWS files or global credentials. Missing profile means stop and ask the
user to choose saved credentials in Settings > S3 Credentials.
This tool provisions a separate pinned environment if needed, stores original
encoded file bytes, and reconstructs them in arraymorph-recovered after verifying
SHA256 in a fresh native worker. Report only its actual evidence. It does not
submit Smart Labeler jobs; use the reconstructed image for a separate staging
step only when the corresponding service integration supports that operation.

ArrayMorph is a Python/native HDF5 VOL connector, not a command named arraymorph.
Use an isolated Python environment inside the pod, never the host laptop or the
agent's own Python environment. Installing instructions is not installing the
package. Do not install packages unless the user requests setup.

For an image, distinguish lossless storage of original encoded bytes in a uint8
dataset from conversion to a pixel array. ArrayMorph stores the uint8 bytes
as an HDF5 dataset in S3, so the uploaded JPEG/PNG does not appear in the
bucket as a standalone .jpg/.png file. Preserve original bytes when a later
Smart Labeler operation needs the original JPEG/PNG. Reconstruct and verify the
SHA256 before staging that file to Smart Labeler; an HDF5 filename is not an
image path for the labeling API.

Read credentials only from a private runtime file or environment. Never print
credentials, put them in conversation history, or write shared global credentials.
Use per-request HOME/config where necessary. Do not inherit another user's keys.
If credentials are unavailable, explain the missing prerequisite without guessing.

Use unique session/run object names in the configured bucket. Do not list all
buckets: this service account may only access its assigned bucket. Do not delete
unrelated objects. Do not fall back to ordinary S3 upload and call it ArrayMorph.

Report separately: instructions available, package installed, native plugin
loaded, cloud write observed, cloud read verified, original file reconstructed,
Smart Labeler staging, job submission. Only report stages actually observed.
Stop on errors and report the last completed stage. Installation/import success
alone does not establish a working HDF5/S3 connector.

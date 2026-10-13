# Smart Labeler API Reference

- Source: `references/openapi.json`
- Upstream: `https://github.com/ICICLE-ai/smart_labeler` at `f7a6f34dd5ba4f9c6f7f6973054b34158a82f4a2`
- OpenAPI: `3.1.0`
- API version: `1.0.0`
- SHA-256: `09ef47c2f98d218df38ecc2df298b071c7a3b1c5cfd0c2f2626987f939939a86`
- Operations: `40`
- Authentication: `Tapis-Token: $TAPIS_TOKEN`
- Base URL: `$SMART_LABELER_BASE_URL`

## Safety Classes

- `safe-read`: execute when required identifiers are supplied.
- `guarded-read`: explain the transfer or possible side effect and get approval.
- `state-changing`: preview the exact request and obtain explicit approval.
- `excluded`: do not invoke from this general-purpose skill.

Permanent deletion requires a second confirmation. HPC submissions require
a preview of model IDs, input/output paths, device, and any resource fields
that the documented request schema actually exposes.

## Current Live Demo Test

Use `GET /pipes` for the current live demo because it has been
observed returning pipeline records with HTTP 200. `GET /is-admin` is
documented in current source, but older deployed revisions have returned
HTTP 500; do not use it as the primary demo health gate.

## Endpoint Index

| Safety | Method | Path | Summary |
| --- | --- | --- | --- |
| `state-changing` | `PUT` | `/annotator-configuration/config/{config_id}` | Update an annotator configuration |
| `state-changing` | `DELETE` | `/annotator-configuration/config/{config_id}` | Delete an annotator configuration |
| `safe-read` | `GET` | `/annotator-configuration/{pipe_id}` | List annotator configurations for a pipeline |
| `state-changing` | `POST` | `/annotator-configuration/{pipe_id}` | Create an annotator configuration |
| `excluded` | `GET` | `/api/vault/secret/{secret_name}` | Read a secret from the Tapis vault (value is masked) |
| `excluded` | `POST` | `/api/vault/secret/{secret_name}` | Store a secret in the Tapis vault |
| `excluded` | `DELETE` | `/api/vault/secret/{secret_name}` | Destroy a secret from the Tapis vault |
| `state-changing` | `GET` | `/cancel-job/{pipeId}/{jobId}` | Cancel a running Tapis job |
| `guarded-read` | `GET` | `/download_job_logs/{job_id}` | Download tapisjob.out log for a job |
| `state-changing` | `POST` | `/generate_class_supports/{ids}` | Submit a Tapis job to generate class support tensors |
| `safe-read` | `GET` | `/get-dir-contents/{digid}/{system}` | List subdirectories and images at a path (single level) |
| `guarded-read` | `GET` | `/get-img/{digid}/{system}` | Fetch an image from Tapis; TIFF is auto-converted to JPEG |
| `safe-read` | `GET` | `/get-imgs-in-dir/{digid}/{system}` | List image paths in a directory (auto-paginated) |
| `excluded` | `POST` | `/get-imgs-in-dir/{digid}/{system}` | (not documented) |
| `safe-read` | `GET` | `/get-object-detection-pipeline/{pipeId}` | Get object detection pipeline config including active query image config |
| `safe-read` | `GET` | `/get_all_query_image_configurations/{pipeId}` | List all query image configurations for a pipeline |
| `guarded-read` | `GET` | `/get_file/{digid}/{system}` | Fetch a single file from Tapis |
| `safe-read` | `GET` | `/get_files/{digid}/{system}` | List files in a Tapis directory |
| `guarded-read` | `POST` | `/get_imgs_batch/{digid}/{system}` | Fetch multiple images in parallel as base64-encoded strings |
| `safe-read` | `GET` | `/get_job_status/{job_id}` | Get the status of a Tapis job |
| `excluded` | `GET` | `/get_object_detection_pipeline/{id}` | Get object detection pipeline (legacy route) |
| `safe-read` | `GET` | `/getimgs/{digid}` | List images and label count for a pipeline data directory |
| `excluded` | `POST` | `/getimgs/{digid}` | (not documented) |
| `safe-read` | `GET` | `/is-admin` | Check whether the authenticated user is an admin |
| `excluded` | `GET` | `/login` | Begin OAuth2 login flow |
| `excluded` | `GET` | `/oauth2/callback` | OAuth2 authorization code callback |
| `state-changing` | `POST` | `/object-classification/{pipeid}/{od_id}` | Submit a Tapis object classification job |
| `state-changing` | `POST` | `/object-detection/{pipeid}/{id}` | Submit a Tapis object detection job; use id=0 to create a new config |
| `safe-read` | `GET` | `/patra/download_mc/{mc_id}` | Fetch a single Patra model card by ID |
| `safe-read` | `GET` | `/patra/list` | List all Patra model cards |
| `state-changing` | `POST` | `/pipe/create` | Create a new pipeline |
| `state-changing` | `DELETE` | `/pipe/delete/{pipe_id}` | Delete a pipeline |
| `state-changing` | `PUT` | `/pipe/update/{pipe_id}` | Update a pipeline |
| `safe-read` | `GET` | `/pipe/{pipe_id}` | Get a single pipeline by ID |
| `guarded-read` | `GET` | `/pipes` | List all pipelines for the authenticated user |
| `state-changing` | `POST` | `/save-file/{system}` | Upload a file to Tapis |
| `excluded` | `GET` | `/tapisui-entry` | TapisUI iframe entry (deprecated) |
| `state-changing` | `POST` | `/update_class_support_tensor_file_path/{ids}` | Update the class support tensor file path for an object detection entry |
| `state-changing` | `POST` | `/update_current_query_image_configuration/{pipeId}/{configId}` | Update a query image configuration |
| `state-changing` | `POST` | `/update_object_detection_entry/{pipeId}` | Update an object detection entry |

## Detailed Operations

### PUT `/annotator-configuration/config/{config_id}`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Update an annotator configuration
- Tags: Annotator
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `config_id` | `path` | `True` | `integer` | `` |

Request body: `AnnotatorConfigUpdate`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `annotationFilePath` | `False` | `string \| null` | `None` |
| `fileType` | `False` | `string \| null` | `None` |
| `srcImgDir` | `False` | `string \| null` | `None` |
| `system` | `False` | `string \| null` | `None` |

Responses: `200`, `422`.

### DELETE `/annotator-configuration/config/{config_id}`

- Safety: `state-changing` - Permanently deletes Smart Labeler state.
- Summary: Delete an annotator configuration
- Tags: Annotator
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `config_id` | `path` | `True` | `integer` | `` |

Responses: `200`, `422`.

### GET `/annotator-configuration/{pipe_id}`

- Safety: `safe-read` - No state change is documented.
- Summary: List annotator configurations for a pipeline
- Tags: Annotator
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipe_id` | `path` | `True` | `integer` | `` |

Responses: `200`, `422`.

### POST `/annotator-configuration/{pipe_id}`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Create an annotator configuration
- Tags: Annotator
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipe_id` | `path` | `True` | `integer` | `` |

Request body: `AnnotatorConfigCreate`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `annotationFilePath` | `True` | `string` | `` |
| `fileType` | `False` | `string` | `default` |
| `srcImgDir` | `True` | `string` | `` |
| `system` | `True` | `string` | `` |

Responses: `201`, `422`.

### GET `/api/vault/secret/{secret_name}`

- Safety: `excluded` - Secret-management operation; keep outside this general-purpose skill.
- Summary: Read a secret from the Tapis vault (value is masked)
- Tags: Vault
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `secret_name` | `path` | `True` | `string` | `` |

Responses: `200`, `422`.

### POST `/api/vault/secret/{secret_name}`

- Safety: `excluded` - Secret-management operation; keep outside this general-purpose skill.
- Summary: Store a secret in the Tapis vault
- Tags: Vault
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `secret_name` | `path` | `True` | `string` | `` |

Request body: `VaultSecretWrite`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `data` | `True` | `object` | `` |

Responses: `422`.

### DELETE `/api/vault/secret/{secret_name}`

- Safety: `excluded` - Secret-management operation; keep outside this general-purpose skill.
- Summary: Destroy a secret from the Tapis vault
- Tags: Vault
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `secret_name` | `path` | `True` | `string` | `` |

Responses: `200`, `422`.

### GET `/cancel-job/{pipeId}/{jobId}`

- Safety: `state-changing` - Cancels a running Tapis job despite using GET.
- Summary: Cancel a running Tapis job
- Tags: Jobs
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipeId` | `path` | `True` | `integer` | `` |
| `jobId` | `path` | `True` | `string` | `` |

Responses: `200`, `422`.

### GET `/download_job_logs/{job_id}`

- Safety: `guarded-read` - Transfers job logs; require a user-specified job ID and destination.
- Summary: Download tapisjob.out log for a job
- Tags: Jobs
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `job_id` | `path` | `True` | `string` | `` |

Responses: `422`.

### POST `/generate_class_supports/{ids}`

- Safety: `state-changing` - Submits an HPC-backed Tapis job.
- Summary: Submit a Tapis job to generate class support tensors
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `ids` | `path` | `True` | `string` | `` |
| `optimize_crop_size` | `query` | `False` | `boolean` | `False` |

Request body: `ClassSupportsRequest`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `annotationFilePath` | `True` | `string` | `` |
| `cropSize` | `False` | `any` | `1024` |
| `crop_sizes` | `False` | `string` | `1024` |
| `device` | `True` | `string` | `` |
| `method` | `True` | `string` | `` |
| `model_ids` | `False` | `string` | `` |
| `name` | `False` | `string` | `` |
| `newPatra` | `False` | `boolean` | `False` |
| `outputDir` | `True` | `string` | `` |
| `srcImgDir` | `True` | `string` | `` |
| `system` | `True` | `string` | `` |

Responses: `422`.

### GET `/get-dir-contents/{digid}/{system}`

- Safety: `safe-read` - No state change is documented.
- Summary: List subdirectories and images at a path (single level)
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |
| `system` | `path` | `True` | `string` | `` |
| `dir` | `query` | `False` | `string` | `` |

Responses: `200`, `422`.

### GET `/get-img/{digid}/{system}`

- Safety: `guarded-read` - Transfers image data; require a user-specified path and destination.
- Summary: Fetch an image from Tapis; TIFF is auto-converted to JPEG
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |
| `system` | `path` | `True` | `string` | `` |
| `imgURL` | `query` | `False` | `string \| null` | `None` |
| `filePath` | `query` | `False` | `string \| null` | `None` |

Responses: `422`.

### GET `/get-imgs-in-dir/{digid}/{system}`

- Safety: `safe-read` - No state change is documented.
- Summary: List image paths in a directory (auto-paginated)
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |
| `system` | `path` | `True` | `string` | `` |
| `dir` | `query` | `True` | `string` | `` |
| `n` | `query` | `False` | `integer` | `50000` |

Responses: `200`, `422`.

### POST `/get-imgs-in-dir/{digid}/{system}`

- Safety: `excluded` - Undescribed duplicate; use the documented GET route.
- Summary: (not documented)
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |
| `system` | `path` | `True` | `string` | `` |
| `dir` | `query` | `True` | `string` | `` |
| `n` | `query` | `False` | `integer` | `50000` |

Responses: `422`.

### GET `/get-object-detection-pipeline/{pipeId}`

- Safety: `safe-read` - No state change is documented.
- Summary: Get object detection pipeline config including active query image config
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipeId` | `path` | `True` | `integer` | `` |

Responses: `200`, `422`.

### GET `/get_all_query_image_configurations/{pipeId}`

- Safety: `safe-read` - No state change is documented.
- Summary: List all query image configurations for a pipeline
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipeId` | `path` | `True` | `integer` | `` |

Responses: `200`, `422`.

### GET `/get_file/{digid}/{system}`

- Safety: `guarded-read` - Transfers file data; require a user-specified path and destination.
- Summary: Fetch a single file from Tapis
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |
| `system` | `path` | `True` | `string` | `` |
| `imgURL` | `query` | `False` | `string \| null` | `None` |
| `filePath` | `query` | `False` | `string \| null` | `None` |

Responses: `422`.

### GET `/get_files/{digid}/{system}`

- Safety: `safe-read` - No state change is documented.
- Summary: List files in a Tapis directory
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |
| `system` | `path` | `True` | `string` | `` |
| `dir` | `query` | `True` | `string` | `` |

Responses: `200`, `422`.

### POST `/get_imgs_batch/{digid}/{system}`

- Safety: `guarded-read` - Read-only batch transfer, but it can return a large base64 payload.
- Summary: Fetch multiple images in parallel as base64-encoded strings
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |
| `system` | `path` | `True` | `string` | `` |

Request body: `BatchImgRequest`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `files` | `True` | `array[string]` | `` |

Responses: `200`, `422`.

### GET `/get_job_status/{job_id}`

- Safety: `safe-read` - No state change is documented.
- Summary: Get the status of a Tapis job
- Tags: Jobs
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `job_id` | `path` | `True` | `string` | `` |

Responses: `200`, `422`.

### GET `/get_object_detection_pipeline/{id}`

- Safety: `excluded` - Legacy route; use GET /get-object-detection-pipeline/{pipeId}.
- Summary: Get object detection pipeline (legacy route)
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `id` | `path` | `True` | `string` | `` |

Responses: `422`.

### GET `/getimgs/{digid}`

- Safety: `safe-read` - No state change is documented.
- Summary: List images and label count for a pipeline data directory
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |

Responses: `200`, `422`.

### POST `/getimgs/{digid}`

- Safety: `excluded` - Undescribed duplicate; use the GET route.
- Summary: (not documented)
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `digid` | `path` | `True` | `string` | `` |

Responses: `422`.

### GET `/is-admin`

- Safety: `safe-read` - No state change is documented.
- Summary: Check whether the authenticated user is an admin
- Tags: Admin
- Authentication: `Tapis-Token`
- Note: Preferred first live test: authenticated database read with a boolean response.

Responses: `200`, `422`.

### GET `/login`

- Safety: `excluded` - Browser OAuth flow; do not invoke as an API tool.
- Summary: Begin OAuth2 login flow
- Tags: Auth
- Authentication: none documented; excluded from agent use unless stated

Responses: `422`.

### GET `/oauth2/callback`

- Safety: `excluded` - OAuth callback; never construct this call.
- Summary: OAuth2 authorization code callback
- Tags: Auth
- Authentication: none documented; excluded from agent use unless stated

Responses: `422`.

### POST `/object-classification/{pipeid}/{od_id}`

- Safety: `state-changing` - Submits an HPC-backed Tapis job.
- Summary: Submit a Tapis object classification job
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipeid` | `path` | `True` | `string` | `` |
| `od_id` | `path` | `True` | `string` | `` |

Request body: `ObjectClassificationRequest`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `class_support_paths` | `True` | `string` | `` |
| `id` | `True` | `integer` | `` |
| `is_query_dir` | `False` | `boolean` | `False` |
| `name` | `False` | `string` | `` |
| `objectnessThreshold` | `True` | `number` | `` |
| `outputDir` | `True` | `string` | `` |
| `proposal_tensor_paths` | `True` | `string` | `` |
| `queryImagePath` | `True` | `string` | `` |
| `similarityThreshold` | `True` | `number` | `` |
| `system` | `True` | `string` | `` |

Responses: `422`.

### POST `/object-detection/{pipeid}/{id}`

- Safety: `state-changing` - Submits an HPC-backed Tapis job.
- Summary: Submit a Tapis object detection job; use id=0 to create a new config
- Tags: ObjectDetection
- Authentication: `Tapis-Token`
- Note: Use id=0 to create a new query-image configuration.

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipeid` | `path` | `True` | `string` | `` |
| `id` | `path` | `True` | `integer` | `` |

Request body: `ObjectDetectionRequest`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `batch_size` | `False` | `integer` | `4` |
| `cores_per_node` | `False` | `integer` | `8` |
| `device` | `True` | `string` | `` |
| `embedder_ids` | `False` | `string` | `4` |
| `is_query_dir` | `False` | `boolean` | `False` |
| `is_sahi` | `False` | `boolean` | `False` |
| `max_minutes` | `False` | `integer` | `210` |
| `memory_mb` | `False` | `integer` | `64800` |
| `method` | `True` | `string` | `` |
| `name` | `False` | `string` | `` |
| `newPatra` | `False` | `boolean` | `False` |
| `nmsIoUThreshold` | `True` | `number` | `` |
| `node_count` | `False` | `integer` | `1` |
| `objectnessThreshold` | `True` | `number` | `` |
| `outputDir` | `True` | `string` | `` |
| `overlap_ratio` | `False` | `number` | `0.2` |
| `proposer_ids` | `False` | `string` | `1` |
| `queryImagePath` | `True` | `string` | `` |
| `similarityThreshold` | `True` | `number` | `` |
| `system` | `True` | `string` | `` |
| `tile_size` | `False` | `integer` | `960` |

Responses: `422`.

### GET `/patra/download_mc/{mc_id}`

- Safety: `safe-read` - No state change is documented.
- Summary: Fetch a single Patra model card by ID
- Tags: Patra
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `mc_id` | `path` | `True` | `string` | `` |

Responses: `422`.

### GET `/patra/list`

- Safety: `safe-read` - No state change is documented.
- Summary: List all Patra model cards
- Tags: Patra
- Authentication: `Tapis-Token`

Responses: `422`.

### POST `/pipe/create`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Create a new pipeline
- Tags: Pipelines
- Authentication: `Tapis-Token`
- Note: The current schema uses slurmaccount, not slurm; the agent policy fixes slurmaccount to uot260.

Request body: `PipelineCreate`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `description` | `False` | `string` | `` |
| `name` | `True` | `string` | `` |
| `slurmaccount` | `False` | `string` | `` |
| `type` | `False` | `string` | `DETECTION` |

Responses: `201`, `422`.

### DELETE `/pipe/delete/{pipe_id}`

- Safety: `state-changing` - Permanently deletes Smart Labeler state.
- Summary: Delete a pipeline
- Tags: Pipelines
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipe_id` | `path` | `True` | `integer` | `` |

Responses: `200`, `422`.

### PUT `/pipe/update/{pipe_id}`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Update a pipeline
- Tags: Pipelines
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipe_id` | `path` | `True` | `integer` | `` |

Request body: `PipelineUpdate`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `description` | `False` | `string \| null` | `None` |
| `name` | `False` | `string \| null` | `None` |
| `slurmaccount` | `False` | `string \| null` | `None` |
| `type` | `False` | `string \| null` | `None` |

Responses: `200`, `422`.

### GET `/pipe/{pipe_id}`

- Safety: `safe-read` - No state change is documented.
- Summary: Get a single pipeline by ID
- Tags: Pipelines
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipe_id` | `path` | `True` | `integer` | `` |

Responses: `200`, `422`.

### GET `/pipes`

- Safety: `guarded-read` - The current server source may create a first-time user row.
- Summary: List all pipelines for the authenticated user
- Tags: Pipelines
- Authentication: `Tapis-Token`

Responses: `200`, `422`.

### POST `/save-file/{system}`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Upload a file to Tapis
- Tags: Files
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `system` | `path` | `True` | `string` | `` |
| `path` | `query` | `True` | `string` | `` |

Responses: `200`, `422`.

### GET `/tapisui-entry`

- Safety: `excluded` - Deprecated iframe entry; not an agent tool.
- Summary: TapisUI iframe entry (deprecated)
- Tags: Auth
- Authentication: none documented; excluded from agent use unless stated

Responses: `422`.

### POST `/update_class_support_tensor_file_path/{ids}`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Update the class support tensor file path for an object detection entry
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `ids` | `path` | `True` | `string` | `` |

Request body: `ClassSupportTensorUpdate`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `class_support_tensor_file_path` | `True` | `string` | `` |
| `crop_size` | `True` | `integer` | `` |

Responses: `200`, `422`.

### POST `/update_current_query_image_configuration/{pipeId}/{configId}`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Update a query image configuration
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipeId` | `path` | `True` | `integer` | `` |
| `configId` | `path` | `True` | `integer` | `` |

Request body: `QueryImageConfigUpdate`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `batch_size` | `False` | `integer \| null` | `None` |
| `class_support_paths` | `False` | `string \| null` | `None` |
| `cores_per_node` | `False` | `integer \| null` | `None` |
| `device` | `False` | `string \| null` | `None` |
| `embedder_ids` | `False` | `string \| null` | `None` |
| `embedder_models` | `False` | `string \| null` | `None` |
| `is_query_dir` | `False` | `boolean \| null` | `None` |
| `is_sahi` | `False` | `boolean \| null` | `None` |
| `max_minutes` | `False` | `integer \| null` | `None` |
| `memory_mb` | `False` | `integer \| null` | `None` |
| `method` | `False` | `string \| null` | `None` |
| `name` | `False` | `string \| null` | `None` |
| `nmsIoUThreshold` | `False` | `number \| null` | `None` |
| `node_count` | `False` | `integer \| null` | `None` |
| `objectnessThreshold` | `False` | `number \| null` | `None` |
| `outputDir` | `False` | `string \| null` | `None` |
| `overlap_ratio` | `False` | `number \| null` | `None` |
| `proposal_tensor_paths` | `False` | `string \| null` | `None` |
| `proposer_ids` | `False` | `string \| null` | `None` |
| `proposer_models` | `False` | `string \| null` | `None` |
| `queryImagePath` | `False` | `string \| null` | `None` |
| `similarityThreshold` | `False` | `number \| null` | `None` |
| `system` | `False` | `string \| null` | `None` |
| `tile_size` | `False` | `integer \| null` | `None` |

Responses: `200`, `422`.

### POST `/update_object_detection_entry/{pipeId}`

- Safety: `state-changing` - Changes Smart Labeler, Tapis, or remote storage state.
- Summary: Update an object detection entry
- Tags: ObjectDetection
- Authentication: `Tapis-Token`

| Parameter | In | Required | Type | Default |
| --- | --- | --- | --- | --- |
| `pipeId` | `path` | `True` | `integer` | `` |

Request body: `ObjectDetectionUpdate`

| Field | Required | Type | Default |
| --- | --- | --- | --- |
| `annotationFilePath` | `False` | `string \| null` | `None` |
| `class_supports_tensor_file_path` | `False` | `string \| null` | `None` |
| `cropSize` | `False` | `integer \| null` | `None` |
| `crop_sizes` | `False` | `string \| null` | `None` |
| `current_query_image_configuration` | `False` | `integer \| null` | `None` |
| `device` | `False` | `string \| null` | `None` |
| `generate_class_supports_job_id` | `False` | `string \| null` | `None` |
| `method` | `False` | `string \| null` | `None` |
| `name` | `False` | `string \| null` | `None` |
| `outputDir` | `False` | `string \| null` | `None` |
| `srcImgDir` | `False` | `string \| null` | `None` |
| `system` | `False` | `string \| null` | `None` |

Responses: `200`, `422`.

## Response Rules

- Report the observed HTTP status and response fields; do not invent fields.
- For `422`, summarize each validation error's `loc`, `msg`, and `type`.
- For binary image, file, or log responses, save only to a user-approved path.
- Never expose the Tapis token or Vault material.
- Never automatically retry a state-changing call.

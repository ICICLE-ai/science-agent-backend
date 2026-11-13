#!/usr/bin/env python3
"""Store a session image with ArrayMorph and optionally submit Smart Labeler work."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from run_autonomous_labeling_setup import (
    BIOCLIP_ID,
    FIXED_SLURM_ACCOUNT,
    OWLV2_ID,
    CurlSmartLabeler,
    SetupError,
    run_setup,
)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
ANNOTATED_DEMO_SOURCE_SHA256 = (
    "907725552128386ac1a733f5318f813bc86385195f9b6075adc6b4b0ac72a588"
)
ANNOTATED_DEMO_FILENAME = "20181001 (114).JPG"
ANNOTATED_DEMO_PATH = "/demo/annotation/ann.json"


PROGRESS_LABELS = {
    "input": "Checking uploaded image",
    "arraymorph": "Storing and verifying the image with ArrayMorph",
    "tapis-stage": "Staging the restored image with Tapis Files",
    "annotation": "Preparing the annotation file",
    "smart-labeler-preflight": "Checking Smart Labeler files and models",
    "preflight": "Checking Smart Labeler files and models",
    "pipeline-create": "Creating the Smart Labeler pipeline",
    "created-pipeline-validation": "Validating the Smart Labeler pipeline",
    "job-submit": "Submitting the Smart Labeler job",
    "job-status": "Checking the submitted job status",
    "workflow": "Completing the labeling workflow",
}


def emit_progress(step_id, status, label=None, detail=None, metadata=None):
    progress_file = os.getenv("SCIENCE_AGENT_PROGRESS_FILE", "").strip()
    if not progress_file:
        return
    payload = {
        "step_id": step_id,
        "label": label or PROGRESS_LABELS.get(step_id, step_id.replace("-", " ").title()),
        "status": status,
        "timestamp": int(time.time()),
    }
    if detail:
        payload["detail"] = str(detail)
    if metadata:
        payload["metadata"] = metadata
    path = Path(progress_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
        handle.flush()


def write_workflow_result(payload):
    result_file = os.getenv("SCIENCE_AGENT_RESULT_FILE", "").strip()
    if not result_file:
        return
    path = Path(result_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def request_json(url, payload=None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SetupError("arraymorph", f"ArrayMorph service returned HTTP {exc.code}: {detail[:800]}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SetupError("arraymorph", f"ArrayMorph service call failed: {exc}") from exc


def choose_image(session_root, session_id, filename=None):
    if not SAFE_ID.fullmatch(session_id):
        raise SetupError("input", "Invalid Science Agent session ID")
    upload_dir = Path(session_root) / session_id / "uploads"
    if filename:
        if Path(filename).name != filename:
            raise SetupError("input", "Image filename must not contain a path")
        candidate = upload_dir / filename
        if not candidate.is_file():
            raise SetupError("input", f"Uploaded image was not found: {filename}")
        return candidate

    images = sorted(
        path for path in upload_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ) if upload_dir.is_dir() else []
    if not images:
        raise SetupError("input", "No uploaded image is available in this session")
    if len(images) > 1:
        raise SetupError("input", "Multiple uploaded images are available; specify one filename")
    return images[0]


def latest_manifest(session_root, session_id):
    manifests = sorted(
        (Path(session_root) / session_id / "arraymorph").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not manifests:
        raise SetupError("arraymorph", "No ArrayMorph dataset exists for this session")
    try:
        return json.loads(manifests[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError("arraymorph", "The latest ArrayMorph manifest is invalid") from exc


def tapis_curl(command, token, input_bytes=None):
    config = f'header = "X-Tapis-Token: {token}"\n'.encode("utf-8")
    result = subprocess.run(
        ["/usr/bin/curl", "--config", "-", *command],
        input=config if input_bytes is None else config + input_bytes,
        capture_output=True,
        check=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        raise SetupError("tapis-stage", (stderr or stdout or "Tapis Files request failed")[:1000])
    try:
        return json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        raise SetupError("tapis-stage", "Tapis Files returned invalid JSON") from exc


def ensure_remote_directory(token, tapis_base_url, system, remote_dir):
    directory_url = (
        f"{tapis_base_url.rstrip('/')}/v3/files/ops/"
        f"{quote(system, safe='')}/{quote(remote_dir.lstrip('/'), safe='/')}"
    )
    try:
        tapis_curl(
            ["--fail-with-body", "--silent", "--show-error", directory_url],
            token,
        )
        return
    except SetupError as exc:
        if "404" not in str(exc):
            raise

    mkdir_url = (
        f"{tapis_base_url.rstrip('/')}/v3/files/ops/"
        f"{quote(system, safe='')}"
    )
    tapis_curl(
        [
            "--fail-with-body",
            "--silent",
            "--show-error",
            "-H",
            "Content-Type: application/json",
            "-X",
            "POST",
            "--data",
            json.dumps({"path": remote_dir}, separators=(",", ":")),
            mkdir_url,
        ],
        token,
    )


def stage_recovered_image(manifest, token, tapis_base_url, system, base_dir):
    recovered = Path(manifest["recovered_path"])
    if not recovered.is_file():
        raise SetupError("tapis-stage", "ArrayMorph recovered image is unavailable")

    remote_dir = "/" + "/".join(
        part
        for part in (
            f"{base_dir}/{manifest['session_id']}/{manifest['dataset_id']}/ground_truth"
        ).split("/")
        if part
    )
    ensure_remote_directory(token, tapis_base_url, system, remote_dir)
    remote_path = f"{remote_dir}/{recovered.name}"
    upload_url = (
        f"{tapis_base_url.rstrip('/')}/v3/files/ops/"
        f"{quote(system, safe='')}/{quote(remote_path.lstrip('/'), safe='/')}"
    )
    upload = tapis_curl(
        [
            "--fail-with-body",
            "--silent",
            "--show-error",
            "-X",
            "POST",
            "-F",
            f"file=@{recovered};type=image/png",
            upload_url,
        ],
        token,
    )

    listing_url = (
        f"{tapis_base_url.rstrip('/')}/v3/files/ops/"
        f"{quote(system, safe='')}/{quote(remote_dir.lstrip('/'), safe='/')}"
    )
    listing = tapis_curl(
        ["--fail-with-body", "--silent", "--show-error", listing_url],
        token,
    )
    records = listing.get("result", []) if isinstance(listing, dict) else []
    observed = any(
        item.get("name") == recovered.name or str(item.get("path", "")).endswith("/" + recovered.name)
        for item in records if isinstance(item, dict)
    )
    if not observed:
        raise SetupError("tapis-stage", "The staged image was not observed in the Tapis directory listing")
    return {
        "system": system,
        "path": remote_path,
        "directory": remote_dir,
        "dataset_root": str(Path(remote_dir).parent),
        "upload_status": upload.get("status", "success") if isinstance(upload, dict) else "success",
        "listing_verified": True,
    }


def upload_json_file(payload, token, tapis_base_url, system, remote_path):
    remote_path = "/" + remote_path.lstrip("/")
    ensure_remote_directory(
        token,
        tapis_base_url,
        system,
        str(Path(remote_path).parent),
    )
    upload_url = (
        f"{tapis_base_url.rstrip('/')}/v3/files/ops/"
        f"{quote(system, safe='')}/{quote(remote_path.lstrip('/'), safe='/')}"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.flush()
        tapis_curl(
            [
                "--fail-with-body",
                "--silent",
                "--show-error",
                "-X",
                "POST",
                "-F",
                f"file=@{handle.name};filename=ann.json;type=application/json",
                upload_url,
            ],
            token,
        )


def prepare_session_annotation(manifest, staged, token, tapis_base_url):
    if manifest.get("source_sha256") != ANNOTATED_DEMO_SOURCE_SHA256:
        return None

    annotation_url = (
        f"{tapis_base_url.rstrip('/')}/v3/files/content/"
        f"{quote(staged['system'], safe='')}/"
        f"{quote(ANNOTATED_DEMO_PATH.lstrip('/'), safe='/')}"
    )
    source = tapis_curl(
        ["--fail-with-body", "--silent", "--show-error", annotation_url],
        token,
    )
    annotations = source.get("annotations") if isinstance(source, dict) else None
    if not isinstance(annotations, list):
        raise SetupError("annotation", "The prepared demo annotation file is invalid")

    recovered_name = Path(staged["path"]).name
    selected = []
    for item in annotations:
        if not isinstance(item, dict) or item.get("image_path") != ANNOTATED_DEMO_FILENAME:
            continue
        rewritten = dict(item)
        rewritten["image_path"] = recovered_name
        selected.append(rewritten)
    if not selected:
        raise SetupError("annotation", "No matching annotations were found for the uploaded demo image")

    annotation_path = f"{staged['dataset_root']}/annotation/ann.json"
    output_dir = f"{staged['dataset_root']}/output"
    upload_json_file(
        {"annotations": selected},
        token,
        tapis_base_url,
        staged["system"],
        annotation_path,
    )
    ensure_remote_directory(
        token,
        tapis_base_url,
        staged["system"],
        output_dir,
    )
    return {
        "path": annotation_path,
        "count": len(selected),
        "output_dir": output_dir,
    }


def response_contains_model(payload, model_id):
    return model_id in json.dumps(payload, separators=(",", ":"))


def submit_smart_labeler(
    manifest,
    staged,
    command,
    client,
    write_marker=None,
    annotation=None,
):
    source_name = Path(manifest["source_filename"]).stem
    pipeline_payload = {
        "name": f"DEMO: {source_name} labeling"[:120],
        "type": "DETECTION",
        "description": "Label an uploaded image stored and verified with ArrayMorph.",
        "slurmaccount": FIXED_SLURM_ACCOUNT,
    }

    if annotation is not None:
        plan = {
            "mode": "autonomous-labeling-demo",
            "user_goal": "Generate class support for the uploaded annotated image",
            "file_context_id": 0,
            "pipeline": pipeline_payload,
            "class_support": {
                "srcImgDir": staged["directory"],
                "annotationFilePath": annotation["path"],
                "system": staged["system"],
                "model_ids": f"{BIOCLIP_ID},{OWLV2_ID}",
                "cropSize": 1024,
                "device": "CUDA",
                "outputDir": annotation["output_dir"],
                "method": "Image",
                "name": "Generate Support embeddings",
                "newPatra": True,
                "crop_sizes": "[1024, 760]",
            },
            "models": [
                {"name": "BioCLIP 2", "uuid": BIOCLIP_ID},
                {"name": "OWLv2 Large Patch14 Ensemble", "uuid": OWLV2_ID},
            ],
            "data_mapping": "ArrayMorph reconstruction staged in a session-scoped Tapis directory.",
        }
        summary = run_setup(
            plan,
            f"/artifacts/arraymorph-class-support-{manifest['session_id']}-{manifest['dataset_id']}",
            client,
            progress=emit_progress,
        )
        summary["annotation"] = {
            "path": annotation["path"],
            "count": annotation["count"],
        }
        summary["request_summary"] = command
        return summary

    emit_progress("smart-labeler-preflight", "running")
    source_files = client.get(
        f"/get_files/0/{staged['system']}",
        {"dir": staged["directory"]},
    )
    observed_source_paths = source_files.get("files", []) if isinstance(source_files, dict) else []
    if not any(str(path).endswith("/" + Path(staged["path"]).name) for path in observed_source_paths):
        raise SetupError("smart-labeler-preflight", "The staged source image was not observed by Smart Labeler")

    models = client.get("/patra/list", {"new": "true"})
    missing_models = [
        model_id for model_id in (BIOCLIP_ID, OWLV2_ID)
        if not response_contains_model(models, model_id)
    ]
    if missing_models:
        raise SetupError("smart-labeler-preflight", "Required Patra model IDs were not observed: " + ", ".join(missing_models))
    emit_progress(
        "smart-labeler-preflight",
        "completed",
        detail="Input image and required Patra models were observed.",
    )

    if write_marker is not None:
        write_marker.touch(exist_ok=False)
    emit_progress("pipeline-create", "running")
    created = client.post("/pipe/create", pipeline_payload)
    try:
        pipeline_id = int(created["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SetupError("pipeline-create", "Smart Labeler did not return an integer pipeline ID") from exc

    created_pipeline = client.get(f"/pipe/{pipeline_id}")
    if (
        not isinstance(created_pipeline, dict)
        or created_pipeline.get("type") != "DETECTION"
        or created_pipeline.get("slurmaccount") != FIXED_SLURM_ACCOUNT
    ):
        raise SetupError("pipeline-create", "Created pipeline did not pass validation")
    emit_progress(
        "pipeline-create",
        "completed",
        detail=f"Pipeline {pipeline_id} was created and validated.",
        metadata={"pipeline_id": pipeline_id},
    )

    detection_body = {
        "queryImagePath": staged["directory"],
        "system": staged["system"],
        "outputDir": f"{staged['dataset_root']}/output",
        "device": "CUDA",
        "method": "Image",
        "objectnessThreshold": 0.3,
        "similarityThreshold": 0.25,
        "nmsIoUThreshold": 0.5,
        "proposer_ids": OWLV2_ID,
        "embedder_ids": BIOCLIP_ID,
        "batch_size": 1,
        "is_query_dir": True,
        "name": f"Label {source_name}"[:120],
        "newPatra": True,
        "is_sahi": False,
        "tile_size": 960,
        "overlap_ratio": 0.2,
        "node_count": 1,
        "cores_per_node": 8,
        "memory_mb": 64800,
        "max_minutes": 210,
    }
    emit_progress("job-submit", "running")
    submitted = client.post(f"/object-detection/{pipeline_id}/0", detection_body)
    if not isinstance(submitted, dict) or submitted.get("status") != "success" or not submitted.get("uuid"):
        raise SetupError("job-submit", "Smart Labeler object detection did not return status=success and a UUID")

    job_id = str(submitted["uuid"])
    emit_progress(
        "job-submit",
        "completed",
        detail=f"Object detection job {job_id} was submitted.",
        metadata={"job_id": job_id},
    )
    emit_progress("job-status", "running")
    status = client.get(f"/get_job_status/{job_id}")
    observed_status = status.get("status") if isinstance(status, dict) else None
    emit_progress(
        "job-status",
        "completed",
        detail=f"Initial job status: {observed_status or 'unknown'}.",
        metadata={"job_id": job_id, "job_status": observed_status},
    )
    return {
        "pipeline": {
            "id": pipeline_id,
            "name": pipeline_payload["name"],
            "type": pipeline_payload["type"],
            "slurmaccount": pipeline_payload["slurmaccount"],
        },
        "job": {
            "uuid": job_id,
            "submission_status": submitted.get("status"),
            "status": status.get("status") if isinstance(status, dict) else None,
            "condition": status.get("condition") if isinstance(status, dict) else None,
            "message": status.get("message") if isinstance(status, dict) else None,
        },
        "input_directory": detection_body["queryImagePath"],
        "output_directory": detection_body["outputDir"],
        "system": detection_body["system"],
        "request_summary": command,
    }


def execute(args, write_marker=None):
    service_url = os.environ["ARRAYMORPH_SERVICE_URL"].rstrip("/")
    session_root = os.getenv("SCIENCE_AGENT_SESSION_ROOT", "/science-agent-sessions")
    manifest = None

    if args.mode in {"store", "run"}:
        emit_progress("input", "running")
        source = choose_image(session_root, args.session_id, args.filename)
        emit_progress(
            "input",
            "completed",
            detail=f"Found uploaded image {source.name}.",
            metadata={"filename": source.name},
        )
        emit_progress("arraymorph", "running")
        manifest = request_json(
            f"{service_url}/v1/datasets/images",
            {"session_id": args.session_id, "filename": source.name},
        )
        emit_progress(
            "arraymorph",
            "completed",
            detail="The image was stored and its round-trip reconstruction was verified.",
            metadata={"dataset_uri": manifest.get("dataset_uri")},
        )
    else:
        emit_progress("arraymorph", "running", detail="Loading the latest session dataset.")
        manifest = latest_manifest(session_root, args.session_id)
        emit_progress(
            "arraymorph",
            "completed",
            detail="Loaded the latest verified ArrayMorph dataset.",
            metadata={"dataset_uri": manifest.get("dataset_uri")},
        )

    result = {"result": "stored", "arraymorph": manifest}
    if args.mode == "store":
        emit_progress("workflow", "completed", detail="ArrayMorph storage workflow completed.")
        return result

    token = os.environ["TAPIS_TOKEN"]
    tapis_base_url = os.getenv("TAPIS_BASE_URL", "https://icicleai.tapis.io")
    tapis_system = os.getenv("SMART_LABELER_TAPIS_SYSTEM", "expanse-tapis-static")
    tapis_base_dir = os.getenv(
        "SMART_LABELER_TAPIS_BASE_DIR",
        "/users/hs950117/demo",
    )
    emit_progress("tapis-stage", "running")
    staged = stage_recovered_image(
        manifest,
        token,
        tapis_base_url,
        tapis_system,
        tapis_base_dir,
    )
    emit_progress(
        "tapis-stage",
        "completed",
        detail=f"Staged and verified {staged['path']}.",
        metadata={"system": staged["system"], "path": staged["path"]},
    )
    annotation = None
    if manifest.get("source_sha256") == ANNOTATED_DEMO_SOURCE_SHA256:
        if write_marker is not None:
            write_marker.touch(exist_ok=False)
            write_marker = None
        emit_progress("annotation", "running")
        annotation = prepare_session_annotation(
            manifest,
            staged,
            token,
            tapis_base_url,
        )
        emit_progress(
            "annotation",
            "completed",
            detail=f"Prepared {annotation['count']} annotation records.",
            metadata={"annotation_path": annotation["path"], "annotation_count": annotation["count"]},
        )
    client = CurlSmartLabeler(
        os.environ["SMART_LABELER_BASE_URL"],
        token,
        "/bench/trace-bin/curl",
    )
    smart_labeler = submit_smart_labeler(
        manifest,
        staged,
        args.command,
        client,
        write_marker=write_marker,
        annotation=annotation,
    )
    result.update(
        {
            "result": "submitted",
            "tapis_staging": staged,
            "smart_labeler": smart_labeler,
        }
    )
    emit_progress("workflow", "completed", detail="The requested workflow was submitted successfully.")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("store", "label", "run"), default="run")
    parser.add_argument("--session-id", default=os.getenv("SCIENCE_AGENT_SESSION_ID", ""))
    parser.add_argument("--filename")
    parser.add_argument("--command", default=os.getenv("SCIENCE_AGENT_USER_REQUEST", ""))
    args = parser.parse_args()
    if not args.session_id:
        raise SystemExit("Science Agent session ID is required")

    lock_name = f"arraymorph-smart-labeler-{args.mode}-{args.session_id}"
    lock = Path("/artifacts") / (re.sub(r"[^A-Za-z0-9._-]", "-", lock_name) + ".lock")
    write_marker = lock.with_suffix(".write-started")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise SystemExit("This workflow mode has already been executed for the session") from exc

    try:
        result = execute(args, write_marker=write_marker)
    except (KeyError, SetupError) as exc:
        if not write_marker.exists():
            lock.rmdir()
        stage = exc.stage if isinstance(exc, SetupError) else "environment"
        failure = {"result": "not-completed", "stage": stage, "reason": str(exc)}
        emit_progress(
            stage,
            "failed",
            label=PROGRESS_LABELS.get(stage),
            detail=str(exc),
        )
        write_workflow_result(failure)
        print(json.dumps(failure, separators=(",", ":")), file=sys.stderr)
        raise SystemExit(1) from exc

    result["observed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_workflow_result(result)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()

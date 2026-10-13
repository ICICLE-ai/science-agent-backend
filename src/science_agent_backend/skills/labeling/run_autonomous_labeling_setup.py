#!/usr/bin/env python3
"""Provision one demo pipeline and submit its first Smart Labeler HPC job."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

from validate_class_support_preflight import (
    validate as validate_preflight,
    validate_resources,
)


BIOCLIP_ID = "8c517ed0-c9c0-4f57-bb9d-f066ab4ec34e"
OWLV2_ID = "04ac0992-d0ab-4a50-8a4f-92a5da89d848"
MODEL_IDS = [BIOCLIP_ID, OWLV2_ID]
FIXED_SLURM_ACCOUNT = "uot260"


class SetupError(RuntimeError):
    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError("plan", f"Could not read valid JSON from {path}: {exc}") from exc


def write_json(path, payload):
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def artifact(prefix, suffix):
    return Path(f"{prefix}-{suffix}.json")


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("mode") != "autonomous-labeling-demo":
        raise SetupError("plan", "Unsupported autonomous labeling plan")
    if plan.get("file_context_id") != 0:
        raise SetupError("plan", "The prepared demo file context must be 0")

    pipeline = plan.get("pipeline")
    if not isinstance(pipeline, dict):
        raise SetupError("plan", "Pipeline payload is missing")
    if set(pipeline) != {"name", "type", "description", "slurmaccount"}:
        raise SetupError("plan", "Pipeline payload has unexpected fields")
    if pipeline.get("type") != "DETECTION":
        raise SetupError("plan", "The captured class-support flow requires DETECTION")
    if pipeline.get("slurmaccount") != FIXED_SLURM_ACCOUNT:
        raise SetupError("plan", f"Pipeline slurmaccount must be {FIXED_SLURM_ACCOUNT}")
    if not str(pipeline.get("name", "")).startswith("DEMO: "):
        raise SetupError("plan", "Demo pipeline name must start with DEMO:")

    body = plan.get("class_support")
    expected_fields = {
        "srcImgDir",
        "annotationFilePath",
        "system",
        "model_ids",
        "cropSize",
        "device",
        "outputDir",
        "method",
        "name",
        "newPatra",
        "crop_sizes",
    }
    if not isinstance(body, dict) or set(body) != expected_fields:
        raise SetupError("plan", "Class-support payload does not match the observed frontend contract")
    expected_values = {
        "system": "expanse-tapis-static",
        "model_ids": ",".join(MODEL_IDS),
        "cropSize": 1024,
        "device": "CUDA",
        "method": "Image",
        "name": "Generate Support embeddings",
        "newPatra": True,
        "crop_sizes": "[1024, 760]",
    }
    if any(body.get(key) != value for key, value in expected_values.items()):
        raise SetupError("plan", "Class-support payload differs from the prepared HAR demo values")

    source_dir = Path(body["srcImgDir"])
    dataset_root = source_dir.parent
    expected_paths = {
        "srcImgDir": str(dataset_root / "ground_truth"),
        "annotationFilePath": str(dataset_root / "annotation" / "ann.json"),
        "outputDir": str(dataset_root / "output"),
    }
    if any(body.get(key) != value for key, value in expected_paths.items()):
        raise SetupError("plan", "Class-support paths must share one dataset root")
    dataset_root_text = str(dataset_root)
    if dataset_root_text != "/demo" and not dataset_root_text.startswith(
        "/users/hs950117/demo/"
    ):
        raise SetupError("plan", "Class-support dataset root is outside the allowed demo area")


class CurlSmartLabeler:
    def __init__(self, base_url, token, curl_path):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.curl_path = curl_path

    def _request(self, method, path, query=None, body=None):
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query)
        command = [
            self.curl_path,
            "--fail-with-body",
            "--silent",
            "--show-error",
            "-H",
            "Accept: application/json",
            "-H",
            f"Tapis-Token: {self.token}",
        ]
        environment = os.environ.copy()
        environment.pop("ALLOW_SMART_LABELER_WRITE_PATH", None)
        if method == "POST":
            environment["ALLOW_SMART_LABELER_WRITE_PATH"] = path
            command.extend(
                [
                    "-X",
                    "POST",
                    "-H",
                    "Content-Type: application/json",
                    "--data",
                    json.dumps(body, separators=(",", ":")),
                ]
            )
        command.append(url)
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env=environment,
        )
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode != 0:
            details = [value for value in (stdout, stderr) if value]
            detail = "\n".join(details) or f"curl exited with {result.returncode}"
            if path == "/pipe/create":
                stage = "pipeline-create"
            elif path.startswith(("/generate_class_supports/", "/object-detection/")):
                stage = "job-submit"
            elif path.startswith("/get_job_status/"):
                stage = "job-status"
            else:
                stage = "preflight"
            raise SetupError(stage, f"{method} {path} failed: {detail[:1000]}")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise SetupError("api", f"{method} {path} returned invalid JSON") from exc

    def get(self, path, query=None):
        return self._request("GET", path, query=query)

    def post(self, path, body):
        return self._request("POST", path, body=body)


def report_progress(progress, step_id, status, detail=None, metadata=None):
    if progress:
        progress(step_id, status, detail=detail, metadata=metadata)


def run_setup(plan, prefix, client, progress=None):
    validate_plan(plan)
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    body = plan["class_support"]
    file_context_id = int(plan["file_context_id"])
    system = body["system"]

    report_progress(progress, "preflight", "running")
    source_files = client.get(
        f"/get_files/{file_context_id}/{system}", {"dir": body["srcImgDir"]}
    )
    write_json(artifact(prefix, "preflight-source-files"), source_files)
    annotation_dir = str(Path(body["annotationFilePath"]).parent)
    annotation_files = client.get(
        f"/get_files/{file_context_id}/{system}", {"dir": annotation_dir}
    )
    write_json(artifact(prefix, "preflight-annotation-files"), annotation_files)
    output_files = client.get(
        f"/get_files/{file_context_id}/{system}", {"dir": body["outputDir"]}
    )
    write_json(artifact(prefix, "preflight-output-files"), output_files)
    models = client.get("/patra/list", {"new": "true"})
    write_json(artifact(prefix, "preflight-models"), models)

    try:
        preflight = validate_resources(
            models,
            MODEL_IDS,
            source_files,
            annotation_files,
            output_files,
            body["srcImgDir"],
            body["annotationFilePath"],
            body["outputDir"],
        )
    except (TypeError, ValueError) as exc:
        raise SetupError("preflight", str(exc)) from exc
    write_json(artifact(prefix, "preflight"), preflight)
    report_progress(
        progress,
        "preflight",
        "completed",
        detail="Source image, annotation, output directory, and Patra models were verified.",
    )

    write_json(artifact(prefix, "pipeline-create-request"), plan["pipeline"])
    report_progress(progress, "pipeline-create", "running")
    created = client.post("/pipe/create", plan["pipeline"])
    write_json(artifact(prefix, "pipeline-create-response"), created)
    try:
        pipeline_id = int(created["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SetupError("pipeline-create", "Pipeline creation did not return an integer id") from exc

    new_pipeline = client.get(f"/pipe/{pipeline_id}")
    write_json(artifact(prefix, "created-pipeline"), new_pipeline)
    try:
        created_preflight = validate_preflight(
            new_pipeline,
            models,
            pipeline_id,
            MODEL_IDS,
            source_files,
            annotation_files,
            output_files,
            body["srcImgDir"],
            body["annotationFilePath"],
            body["outputDir"],
        )
    except (TypeError, ValueError) as exc:
        raise SetupError("created-pipeline-validation", str(exc)) from exc
    write_json(artifact(prefix, "created-pipeline-preflight"), created_preflight)
    report_progress(
        progress,
        "pipeline-create",
        "completed",
        detail=f"Pipeline {pipeline_id} was created and validated.",
        metadata={"pipeline_id": pipeline_id},
    )

    write_json(artifact(prefix, "class-support-request"), body)
    report_progress(progress, "job-submit", "running")
    submitted = client.post(f"/generate_class_supports/{pipeline_id}", body)
    write_json(artifact(prefix, "class-support-response"), submitted)
    if not isinstance(submitted, dict) or submitted.get("status") != "success" or not submitted.get("uuid"):
        raise SetupError(
            "job-submit",
            "Class-support submission did not return status=success and a uuid",
        )
    job_id = str(submitted["uuid"])
    report_progress(
        progress,
        "job-submit",
        "completed",
        detail=f"Class-support job {job_id} was submitted.",
        metadata={"job_id": job_id},
    )

    report_progress(progress, "job-status", "running")
    status = client.get(f"/get_job_status/{job_id}")
    write_json(artifact(prefix, "job-status"), status)
    if not isinstance(status, dict) or not status.get("status"):
        raise SetupError("job-status", "Job status response did not contain status")
    report_progress(
        progress,
        "job-status",
        "completed",
        detail=f"Initial job status: {status.get('status')}.",
        metadata={"job_id": job_id, "job_status": status.get("status")},
    )

    summary = {
        "result": "submitted",
        "user_goal": plan["user_goal"],
        "data_mapping": plan["data_mapping"],
        "pipeline": {
            "id": pipeline_id,
            "name": new_pipeline.get("name", plan["pipeline"]["name"]),
            "type": new_pipeline.get("type"),
            "slurmaccount": new_pipeline.get("slurmaccount"),
        },
        "models": plan["models"],
        "job": {
            "submission_status": submitted["status"],
            "uuid": job_id,
            "status": status.get("status"),
            "condition": status.get("condition"),
            "message": status.get("message"),
            "execSystemId": status.get("execSystemId"),
            "execSystemOutputDir": status.get("execSystemOutputDir"),
        },
    }
    write_json(artifact(prefix, "summary"), summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--artifact-prefix", required=True)
    parser.add_argument("--curl", default="/bench/trace-bin/curl")
    args = parser.parse_args()

    prefix = Path(args.artifact_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    lock = Path(f"{prefix}-execution.lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise SystemExit("This autonomous setup command has already been executed") from exc

    try:
        plan = read_json(args.plan)
        base_url = os.environ["SMART_LABELER_BASE_URL"]
        token = os.environ["TAPIS_TOKEN"]
        client = CurlSmartLabeler(base_url, token, args.curl)
        summary = run_setup(plan, prefix, client)
    except (KeyError, SetupError) as exc:
        stage = exc.stage if isinstance(exc, SetupError) else "environment"
        failure = {
            "result": "not-submitted",
            "stage": stage,
            "reason": str(exc),
            "pipeline_created": artifact(prefix, "pipeline-create-response").exists(),
            "job_submitted": artifact(prefix, "class-support-response").exists(),
        }
        write_json(artifact(prefix, "failure"), failure)
        print(json.dumps(failure, separators=(",", ":")), file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(summary, separators=(",", ":")))


if __name__ == "__main__":
    main()

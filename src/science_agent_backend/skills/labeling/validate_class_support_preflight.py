#!/usr/bin/env python3
"""Validate live pipeline and Patra reads before class-support submission."""

import argparse
import json
from pathlib import Path


FIXED_SLURM_ACCOUNT = "uot260"


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read valid JSON from {path}: {exc}") from exc


def normalize_tapis_path(path):
    return "/" + str(path).lstrip("/")


def observed_files(payload, label):
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise ValueError(f"{label} response must contain a files list")
    return {
        normalize_tapis_path(path)
        for path in payload["files"]
        if isinstance(path, str) and path.strip()
    }


def validate_pipeline(pipeline, pipeline_id):
    if not isinstance(pipeline, dict):
        raise ValueError("Pipeline response must be a JSON object")
    if int(pipeline.get("pid", -1)) != pipeline_id:
        raise ValueError("Pipeline response pid does not match the requested ID")
    if pipeline.get("type") != "DETECTION":
        raise ValueError("Class-support submission requires a DETECTION pipeline")
    if pipeline.get("slurmaccount") != FIXED_SLURM_ACCOUNT:
        raise ValueError(
            f"Pipeline slurmaccount must be {FIXED_SLURM_ACCOUNT}"
        )
    return {
        "pipeline_id": pipeline_id,
        "pipeline_type": pipeline["type"],
        "slurmaccount": pipeline["slurmaccount"],
    }


def validate_resources(
    models,
    model_ids,
    source_response,
    annotation_response,
    output_response,
    source_dir,
    annotation_file,
    output_dir,
):
    source_dir = normalize_tapis_path(source_dir).rstrip("/")
    annotation_file = normalize_tapis_path(annotation_file)
    output_dir = normalize_tapis_path(output_dir).rstrip("/")
    source_files = observed_files(source_response, "Source directory")
    annotation_files = observed_files(annotation_response, "Annotation directory")
    observed_files(output_response, "Output directory")
    if not any(path.startswith(source_dir + "/") for path in source_files):
        raise ValueError(f"No source files were observed under {source_dir}")
    if annotation_file not in annotation_files:
        raise ValueError(f"Annotation file was not observed: {annotation_file}")
    if not isinstance(models, list):
        raise ValueError("Patra response must be a JSON list")

    observed = {
        item.get("uuid")
        for item in models
        if isinstance(item, dict) and item.get("uuid")
    }
    missing = [model_id for model_id in model_ids if model_id not in observed]
    if missing:
        raise ValueError(
            "Requested Patra model UUIDs were not observed: " + ",".join(missing)
        )

    return {
        "model_ids_observed": model_ids,
        "source_dir": source_dir,
        "source_file_count": len(source_files),
        "annotation_file": annotation_file,
        "output_dir": output_dir,
        "ready_for_single_submission": True,
    }


def validate(
    pipeline,
    models,
    pipeline_id,
    model_ids,
    source_response,
    annotation_response,
    output_response,
    source_dir,
    annotation_file,
    output_dir,
):
    result = validate_pipeline(pipeline, pipeline_id)
    result.update(
        validate_resources(
            models,
            model_ids,
            source_response,
            annotation_response,
            output_response,
            source_dir,
            annotation_file,
            output_dir,
        )
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--source-files", required=True)
    parser.add_argument("--annotation-files", required=True)
    parser.add_argument("--output-files", required=True)
    parser.add_argument("--pipeline-id", required=True, type=int)
    parser.add_argument("--model-id", action="append", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--annotation-file", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    try:
        result = validate(
            load_json(args.pipeline),
            load_json(args.models),
            args.pipeline_id,
            args.model_id,
            load_json(args.source_files),
            load_json(args.annotation_files),
            load_json(args.output_files),
            args.source_dir,
            args.annotation_file,
            args.output_dir,
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()

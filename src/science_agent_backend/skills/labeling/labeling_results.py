"""Read completed Smart Labeler outputs without starting another workflow."""
from collections import Counter
import math
from pathlib import PurePosixPath


def summarize_annotations(document):
    if not isinstance(document, dict) or not isinstance(document.get('annotations'), list):
        raise ValueError('Unsupported JSON schema: expected an annotations array.')
    annotations = document['annotations']
    categories = {str(item['id']): str(item.get('name', item['id']))
                  for item in document.get('categories', [])
                  if isinstance(item, dict) and 'id' in item}
    labels, images, scores = Counter(), Counter(), []
    missing_scores = 0
    score_valued_labels = 0
    for item in annotations:
        if not isinstance(item, dict) or not any(key in item for key in ('bounding_box', 'bbox', 'segmentation')):
            raise ValueError('Unsupported annotation entry: no box or segmentation.')
        label = item.get('class', categories.get(str(item.get('category_id'))))
        labels[str(label) if label is not None else '(unlabeled)'] += 1
        image = item.get('image_path', item.get('image_id', '(unspecified)'))
        images[str(image)] += 1
        score = item.get('score')
        try:
            if label is not None and score is not None and math.isclose(float(label), float(score)):
                score_valued_labels += 1
        except (TypeError, ValueError):
            pass
        if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
            scores.append(score)
        else:
            missing_scores += 1
    return {
        'annotation_count': len(annotations), 'class_counts': dict(labels),
        'annotations_per_image': dict(images), 'scored_annotation_count': len(scores),
        'missing_score_count': missing_scores,
        'score_valued_label_count': score_valued_labels,
        'scores': {'min': min(scores), 'mean': sum(scores) / len(scores), 'max': max(scores)} if scores else None,
        'limitations': 'Model scores are not measured accuracy. Proposals are not verified species classifications. Human review is still required.',
    }


def inspect_results(client, job_id, saved, output_dir=None):
    status = client.get('/get_job_status/' + job_id)
    result = {'job_id': job_id, 'response': status, 'result_analysis': {'state': 'not_completed'}}
    if not isinstance(status, dict) or str(status.get('status', '')).upper() not in {'FINISHED', 'COMPLETED'}:
        return result
    root = output_dir or saved.get('output_directory')
    system = saved.get('system') or client.context.get('tapis_system')
    if not root or not system:
        result['result_analysis'] = {'state': 'missing_output_location',
                                     'detail': 'Job completed, but its recorded output directory/system is unavailable. Ask for the job output location; do not guess.'}
        return result
    root = str(root).removeprefix('tapis://')
    if '..' in PurePosixPath(root).parts or not root.startswith('/'):
        raise ValueError('Invalid output directory.')
    pipeline_id = (saved.get('pipeline') or {}).get('id', 0)
    kind = saved.get('result_kind', 'proposals')
    subdir = {'proposals': 'proposals/generated_boxes', 'classification': 'detections',
              'class-support': 'class_supports/generated_boxes'}.get(kind)
    if subdir is None:
        raise ValueError('Unknown recorded result kind.')
    directories = [str(PurePosixPath(root) / subdir), root]
    analysis = {'state': 'no_json_outputs', 'kind': kind, 'output_directory': root,
                'system': system, 'files': [], 'errors': []}
    result['result_analysis'] = analysis
    for directory in directories:
        try:
            listing = client.get(f'/get_files/{pipeline_id}/{system}', {'dir': directory})
            if not isinstance(listing, dict) or not isinstance(listing.get('files'), list):
                raise ValueError('Invalid file listing.')
            paths = sorted(set(p for p in listing['files'] if isinstance(p, str) and p.lower().endswith('.json')))
        except (RuntimeError, ValueError) as exc:
            analysis['errors'].append({'path': directory, 'error': str(exc)})
            continue
        if not paths:
            continue
        analysis['listed_json_count'] = len(paths)
        analysis['truncated'] = len(paths) > 20
        for raw in paths[:20]:
            path = raw.removeprefix('tapis://')
            if not path.startswith('/'):
                path = '/' + path
            if '..' in PurePosixPath(path).parts or PurePosixPath(path).parent != PurePosixPath(directory):
                analysis['errors'].append({'path': raw, 'error': 'Result path is outside the listed directory.'})
                continue
            try:
                document = client.get(f'/get_file/{pipeline_id}/{system}', {'filePath': path})
                analysis['files'].append({'path': path, **summarize_annotations(document)})
            except (RuntimeError, ValueError) as exc:
                analysis['errors'].append({'path': path, 'error': str(exc)})
        break
    if analysis['files']:
        analysis['state'] = 'partial' if analysis['errors'] or analysis['truncated'] else 'analyzed'
        analysis['detail'] = 'Report each JSON separately: different model outputs may contain the same objects. Do not sum them as unique objects.'
    elif analysis['errors']:
        analysis['state'] = 'results_unavailable'
    return result

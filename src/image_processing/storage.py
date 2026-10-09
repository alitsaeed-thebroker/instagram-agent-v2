"""Persistence for validated image-processing plans."""

from pathlib import Path
import json

from src.image_processing.schema import ImageProcessingPlanCollection
from src.utils.config import IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY


def save_image_processing_plans(collection: ImageProcessingPlanCollection, project: str, output_root: Path = IMAGE_PROCESSING_PLANS_OUTPUT_DIRECTORY) -> Path:
    errors = collection.validate()
    if errors:
        raise ValueError("Cannot save invalid image processing plans: " + "; ".join(errors))
    if any(plan.project != project for plan in collection.image_processing_plans):
        raise ValueError("Cannot save cross-project image processing plans")
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"{project}-image-processing-plans.json"
    payload = json.loads(collection.to_json())
    payload["project_id"] = project
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination

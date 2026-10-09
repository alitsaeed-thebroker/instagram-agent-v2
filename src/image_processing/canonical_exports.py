"""Carry Department 3's approved publication dimensions into processing."""
from src.image_processing.schema import ExportVariant
from src.knowledge.consumer import require_canonical_graph
from src.execution.lineage import canonical_graph_fingerprint,require_lineage,artifact_fingerprint
from src.publication import normalize_publication_type

def align_canonical_exports(collection,content,knowledge,project,root=None):
    if content.get('project_id')!=project:raise ValueError('Processing content plan belongs to another project')
    require_canonical_graph(knowledge,expected_project=project)
    from src.execution.lineage import require_content_plan_lineage
    from src.utils.config import PROJECT_ROOT
    require_content_plan_lineage(content,knowledge,root or PROJECT_ROOT,project)
    ideas={x['content_idea_id']:x for x in content.get('content_ideas',[])}
    for plan in collection.image_processing_plans:
        if plan.project!=project:raise ValueError('Processing item belongs to another project')
        idea=ideas.get(plan.content_idea_id)
        if not idea:raise ValueError('Processing item is absent from canonical content plan')
        if not set(plan.source_asset_ids)<=set(idea.get('selected_source_asset_ids',[])):raise ValueError('Processing source is not selected by canonical content plan')
        publication=idea.get('planned_publication') or {}
        platform=str(publication.get('platform') or '').casefold()
        kind=normalize_publication_type(publication.get('publication_type') or idea.get('selected_format'))
        if platform!='instagram':continue
        variants={'single_post':('Instagram Feed',1080,1350,'4:5'),'carousel':('Instagram Carousel',1080,1350,'4:5'),'story':('Instagram Story',1080,1920,'9:16')}
        if kind not in variants:continue
        label,w,h,ratio=variants[kind]
        if (publication.get('width'),publication.get('height'),publication.get('aspect_ratio'))!=(w,h,ratio):raise ValueError('Canonical publication dimensions are invalid')
        if platform not in {str(x).casefold() for x in idea.get('planned_destinations',[])}:raise ValueError('Canonical publication destination is not authorized')
        from src.image_prompts.generator import _authorization
        variant=ExportVariant(label,w,h,ratio,'PNG',90)
        from dataclasses import asdict
        allowed,reason=_authorization(asdict(variant),idea,{})
        if not allowed:raise ValueError('Canonical publication export rejected: '+reason)
        plan.export_variants=[variant]
        for operation in plan.source_asset_operations:
            operation.resize={**operation.resize,'target_dimensions':[{'width':w,'height':h}]}
            operation.output_preparation={**operation.output_preparation,'output_format':'PNG'}
        plan.provenance.update(canonical_content_plan_fingerprint=str(content.get('artifact_fingerprint') or artifact_fingerprint(content)),resize_dimensions=[{'width':w,'height':h}],output_formats=['PNG'])
    return collection

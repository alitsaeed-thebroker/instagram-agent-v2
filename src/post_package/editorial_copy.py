"""Source-bound project editorial copy, applied before artifact lineage is signed."""
import json,hashlib
from pathlib import Path

def copy_path(root,project):
    if not project or any(c in project for c in '/\\') or project in {'.','..'}:raise ValueError('Invalid copy project')
    return Path(root)/'input'/'editorial-copy'/f'{project}.json'

def apply_copy(root,project,items,eligible,ctx,*,alt=False):
    path=copy_path(root,project)
    if not path.is_file():return
    raw=path.read_bytes();config=json.loads(raw)
    if config.get('project_id')!=project or config.get('version')!='1.0.0':raise ValueError('Editorial copy belongs to another project or version')
    assets={a.get('asset_id'):a for a in ctx['assets'].get('assets',[])}
    for item in items:
        members=[eligible[item['branded_item_id']]] if alt else [eligible[x] for x in item.get('branded_item_ids',[])]
        ids={a for m in members for a in m.get('source_asset_ids',[])}
        idea_id=members[0].get('content_idea_id') if alt else item.get('content_idea_id')
        overrides=[x for x in config.get('items',[]) if x.get('content_idea_id')==idea_id and x.get('language_code')==item.get('language_code')]
        if len(overrides)>1:raise ValueError('Ambiguous editorial copy')
        if not overrides:continue
        copy=overrides[0];asset=assets.get(copy.get('asset_id'),{})
        if ids!={copy.get('asset_id')} or asset.get('project_id')!=project or asset.get('source_hash')!=copy.get('source_hash'):raise ValueError('Editorial copy source binding is stale or belongs to another project')
        if alt:
            text=copy['alt_text']
            if not isinstance(text,str) or not 40<=len(text)<=300:raise ValueError('Invalid editorial alt text')
            item.update(alt_text=text,character_count=len(text))
        elif item.get('package_type')!='story':
            for key in ('headline','body','CTA'):
                if not isinstance(copy.get(key),str) or '\ufffd' in copy[key]:raise ValueError('Invalid editorial caption')
                item[key]=copy[key]
            text='\n\n'.join(item[k] for k in ('headline','body','CTA') if item[k]);item.update(full_caption=text,word_count=len(text.split()),character_count=len(text),warnings=[])
        if not alt and copy.get('publication_role'):
            if copy['publication_role']!='project_overview':raise ValueError('Unsupported editorial role')
            item['editorial_publication_role']='project_overview'
        item['editorial_copy_sha256']=hashlib.sha256(raw).hexdigest()

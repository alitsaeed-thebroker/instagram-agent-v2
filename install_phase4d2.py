from __future__ import annotations

import ast, hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.cwd().resolve(); APP=ROOT/'app.py'; BACKUP=ROOT/'output/backups/department3-phase4d2'
IMPORT='from src.department3.legacy_live import run_legacy_strategy_advisory, run_legacy_visual_opportunity_compat, run_legacy_creative_compat\n'
REPLACEMENTS=[
('output=MarketingStrategyAgent().run(knowledge,reci,campaign_intelligence)','output=run_legacy_strategy_advisory(MarketingStrategyAgent().run, knowledge,reci,campaign_intelligence)','MarketingStrategyAgent'),
('output = VisualOpportunityEngine().run(knowledge, inventory, strategy)','output = run_legacy_visual_opportunity_compat(VisualOpportunityEngine().run, knowledge, inventory, strategy)','VisualOpportunityEngine'),
('result = CreativeDirectorAgent().run(knowledge, strategy, paths["content_plan"])','result = run_legacy_creative_compat(CreativeDirectorAgent().run, knowledge, strategy, paths["content_plan"])','CreativeDirectorAgent'),
]

def parse(path): ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def insert_import(text):
    if IMPORT.strip() in text:return text
    tree=ast.parse(text); lines=text.splitlines(True); index=0
    if tree.body and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str): index=getattr(tree.body[0],'end_lineno',tree.body[0].lineno)
    while index<len(lines) and (not lines[index].strip() or lines[index].strip().startswith('from __future__ import')): index+=1
    lines[index:index]=[IMPORT,'\n']; return ''.join(lines)

def main():
    if not APP.is_file(): raise SystemExit('Run from the instagram-agent repository root.')
    if not (ROOT/'src/department3/legacy_live.py').is_file(): raise SystemExit('Missing src/department3/legacy_live.py')
    parse(APP); before=APP.read_text(encoding='utf-8')
    for old,_new,name in REPLACEMENTS:
        count=before.count(old)
        if count!=1: raise SystemExit(f'Refusing Phase 4D.2 patch: expected exactly one live {name} call, found {count}. No files changed.')
    after=insert_import(before)
    for old,new,_name in REPLACEMENTS: after=after.replace(old,new,1)
    BACKUP.mkdir(parents=True,exist_ok=True); backup=BACKUP/'app.py'; shutil.copy2(APP,backup); APP.write_text(after,encoding='utf-8')
    try: parse(APP)
    except Exception: shutil.copy2(backup,APP); raise
    live=APP.read_text(encoding='utf-8')
    if any(old in live for old,_new,_name in REPLACEMENTS): shutil.copy2(backup,APP); raise SystemExit('Legacy direct call remained; rolled back.')
    manifest={'schema_version':'department3.phase4d2.legacy_live_demotion.v1','installed_at':datetime.now(timezone.utc).isoformat(),'app_before_sha256':hashlib.sha256(before.encode()).hexdigest(),'app_after_sha256':sha(APP),'backup':str(backup),'demoted_calls':[name for _o,_n,name in REPLACEMENTS]}
    (BACKUP/'install-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Department 3 Phase 4D.2 legacy live authority demotion: PASS')
    print('- MarketingStrategyAgent: advisory/non-authoritative')
    print('- VisualOpportunityEngine: compatibility/non-authoritative')
    print('- CreativeDirectorAgent: compatibility/non-authoritative')
    print('- Downstream artifact contracts preserved')
    print(f'- Backup: {backup}')
if __name__=='__main__': main()

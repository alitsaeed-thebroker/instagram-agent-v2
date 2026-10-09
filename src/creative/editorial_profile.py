"""Project-owned design preferences; never an authority for facts or assets."""
import json
from pathlib import Path
from PIL import Image,ImageOps
from src.utils.text_layout import fit_layout_text

PROFILE_VERSION='1.0.0'
PROFILE_NAME='architecture_first_editorial'

def profile_path(root,project):
    if Path(project).name!=project or '/' in project or '\\' in project:raise ValueError('Invalid project profile name')
    return Path(root)/'input'/'creative-direction'/f'{project}.json'

def load_editorial_profile(root,project):
    path=profile_path(root,project)
    if not path.is_file():return None
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('project_id')!=project:raise ValueError('Creative direction profile belongs to another project')
    if value.get('profile')!=PROFILE_NAME or value.get('version')!=PROFILE_VERSION:raise ValueError('Unsupported creative direction profile')
    if not isinstance(value.get('excluded_source_assets',[]),list):raise ValueError('Invalid creative source exclusions')
    for item in value.get('excluded_source_assets',[]):
        if not isinstance(item,dict) or not all(isinstance(item.get(k),str) and item[k] for k in ('asset_id','source_hash','reason')):raise ValueError('Creative source exclusions need an asset ID, source hash and reason')
    return value

def apply_architecture_editorial(contract,brand,source_size):
    """Full source fit, clear canvas margins, identity outside architecture."""
    cw,ch=contract['canvas']['width'],contract['canvas']['height']
    story=contract.get('publication_type')=='story'
    if (cw,ch) not in {(1080,1350),(1080,1920)}:raise ValueError('Editorial profile currently supports Instagram 4:5 and 9:16 only')
    frame=(48,280,984,984) if story else (48,120,984,870)
    fitted=ImageOps.contain(Image.new('L',source_size),(frame[2],frame[3]));fw,fh=fitted.size
    placement=[frame[0]+(frame[2]-fw)//2,frame[1]+(frame[3]-fh)//2,fw,fh]
    contract['source_image'].update(crop_mode='fit',placement=placement,protected_regions=[placement[:2]+[placement[0]+fw,placement[1]+fh]])
    footer_y=1440 if story else 1090
    clear=brand.get('logo_clear_space',12);lw=brand.get('minimum_logo_size',120);lh=round(lw/brand.get('logo_aspect_ratio',1))
    contract['brand_logo'].update(x=cw-72-lw,y=footer_y,width=lw,height=lh,clear_space=clear,prominence='restrained')
    title=contract['project_identity'];title.update(x=72,y=footer_y+max(0,(lh-40)//2),width=cw-72-lw-clear-144,height=80,font_size=32,color='#111111',background_support='none')
    rendered,size=fit_layout_text(title['text'],title['width'],title['height'],32,bold=True,rtl=title.get('alignment')=='right',max_lines=2)
    title.update(render_text=rendered,font_size=size)
    for field in ('location','developer_identity','headline','subheadline','supporting_copy','cta'):
        contract[field].update(visible=False,text=None,render_text='')
    contract['composition'].update(strategy='luxury_brochure_layout',visual_style=PROFILE_NAME,information_density='very_low')
    contract['graphics'].update(overlay='none',overlay_geometry=[0,footer_y-24,cw,min(ch,footer_y+lh+clear+24)],footer=True,header=False,rail=False)
    contract['public_copy']={'project_name':title['text'],'headline':None,'subheadline':None,'cta':None,'website':None}
    contract['typography'].update(project_size=size,headline_size=0)
    contract['provenance']['editorial_profile_version']=PROFILE_VERSION
    return contract

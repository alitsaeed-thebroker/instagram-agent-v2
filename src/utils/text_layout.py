"""Shared glyph measurement for authoritative layouts and deterministic rendering."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

TEXT_FIELDS=('project_identity','location','developer_identity','headline','subheadline','supporting_copy','cta')

def layout_font(size, *, bold=False, rtl=False):
    windows=Path('C:/Windows/Fonts')
    names=(['segoeuib.ttf','tahomabd.ttf','arialbd.ttf'] if bold else ['segoeui.ttf','tahoma.ttf','arial.ttf']) if rtl else (['segoeuib.ttf','arialbd.ttf'] if bold else ['segoeui.ttf','arial.ttf'])
    for name in names+['DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf']:
        try:return ImageFont.truetype(str(windows/name) if (windows/name).is_file() else name,max(10,size))
        except OSError:pass
    return ImageFont.load_default()

def text_bounds(item, name):
    rtl=item.get('alignment')=='right'
    font=layout_font(int(item['font_size']),bold=name in {'project_identity','headline'},rtl=rtl)
    anchor='ra' if rtl else 'ma' if item.get('alignment')=='center' else 'la'
    x=item['x']+item['width'] if rtl else item['x']+item['width']/2 if anchor=='ma' else item['x']
    text=str(item.get('render_text') or item.get('text') or '')
    draw=ImageDraw.Draw(Image.new('L',(1,1)))
    spacing=max(2,round(font.size*.12))
    raw=draw.multiline_textbbox((x,0),text,font=font,anchor=anchor,align=item.get('alignment','left'),spacing=spacing)
    y=item['y']-raw[1]
    box=draw.multiline_textbbox((x,y),text,font=font,anchor=anchor,align=item.get('alignment','left'),spacing=spacing)
    return box,font,anchor,x,text,y

def fit_layout_text(text, width, height, size, *, bold=False, rtl=False, max_lines=2):
    draw=ImageDraw.Draw(Image.new('L',(1,1)))
    for candidate_size in range(size,13,-1):
        font=layout_font(candidate_size,bold=bold,rtl=rtl);lines=[]
        for word in str(text).split():
            if not lines:lines=[word];continue
            candidate=lines[-1]+' '+word
            box=draw.textbbox((0,0),candidate,font=font)
            if box[2]-box[0]<=width:lines[-1]=candidate
            else:lines.append(word)
        rendered='\n'.join(lines)
        box=draw.multiline_textbbox((0,0),rendered,font=font,anchor='la',spacing=max(2,round(font.size*.12)))
        if len(lines)<=max_lines and box[2]-box[0]<=width and box[3]-box[1]<=height:
            return rendered,candidate_size
    raise ValueError('Authoritative text cannot fit legibly within its layout box')

def validate_text_layout(contract):
    errors=[];boxes=[]
    for name in TEXT_FIELDS:
        item=contract.get(name,{})
        if not item.get('visible'):continue
        try:
            bounds,_,_,_,text,_=text_bounds(item,name)
            if ' '.join(text.split())!=' '.join(str(item.get('text') or '').split()):errors.append(f'{name} rendered text changes approved copy')
            x,y,w,h=(item[k] for k in ('x','y','width','height'))
            if bounds[0]<x-1 or bounds[1]<y-1 or bounds[2]>x+w+1 or bounds[3]>y+h+1:errors.append(f'{name} glyphs overflow layout box')
            boxes.append((name,(x,y,x+w,y+h)))
        except (KeyError,TypeError,ValueError):errors.append(f'{name} has invalid text layout')
    logo=contract.get('brand_logo',{})
    if logo.get('visible'):
        c=logo.get('clear_space',0);x,y,w,h=(logo.get(k,0) for k in ('x','y','width','height'))
        boxes.append(('brand_logo clear space',(x-c,y-c,x+w+c,y+h+c)))
    for i,(name,a) in enumerate(boxes):
        for other,b in boxes[i+1:]:
            if min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1]):errors.append(f'{name} overlaps {other}')
    return errors

"""Original bright, thread-led studies applying the supplied composition/motion principles."""
import math
import random
from PIL import Image, ImageDraw, ImageFont

from .design import FONT, BOLD_FONT, states

PALETTES={'mint':('#F0F8F2','#146653','#122D2B'),
          'sky':('#F0F6FF','#365ABB','#17223E'),
          'coral':('#FFF3EF','#A44539','#352B2A')}


def frame_image(scene,frame,cfg):
    w,h=cfg['width'],cfg['height']; sx,sy=w/1920,h/1080
    p=scene['params']; bg,accent,ink=PALETTES[p.get('palette','mint')]
    im=Image.new('RGB',(w,h),bg); d=ImageDraw.Draw(im)
    boxes=[]; shapes=[]
    scale=p.get('font_scale',1)
    font=ImageFont.truetype(FONT,max(10,round(30*sy*scale)))
    big=ImageFont.truetype(BOLD_FONT,max(10,round(86*sy*scale)))
    label=ImageFont.truetype(BOLD_FONT,max(10,round(34*sy*scale)))
    def rect(box): return [round(box[0]*sx),round(box[1]*sy),round(box[2]*sx),round(box[3]*sy)]
    def text(x,y,value,f,color=ink,anchor=None):
        at=(round(x*sx),round(y*sy)); kw={'font':f,'anchor':anchor}
        bounds=d.textbbox(at,value,**kw); boxes.append(list(bounds)); d.text(at,value,fill=color,**kw)
    text(150,105,'A SMALL STUDY IN CLEAR COMMUNICATION',font,accent)
    text(150,172,'Find the clear path.',big)
    strategy=p.get('visual_strategy','routing')
    text(150,290,{'routing':'One thread. A deliberate destination.',
                  'connected_route':'The same thread carries the idea through.',
                  'constellation':'Separate signals become one direction.',
                  'fold':'A simple fold opens a new route.'}.get(strategy,'One clear idea.'),font)
    # A continuous purposeful trace under the dominant subject, not a camera-motion trick.
    # Complete the trace before the final ten-frame readable hold.
    q=min(1,frame/80)
    route=[(150,835),(550,835),(700,780),(1110,780),(1350,835),(1765,835)]
    if strategy=='connected_route':
        a,hero,b=states(scene,frame)
        route=[(a['x'],a['y']),(hero['x']-hero['size']/2,hero['y']),
               (hero['x']+hero['size']/2,hero['y']),(b['x'],b['y'])]
    route=[(round(x*sx),round(y*sy)) for x,y in route]
    d.line(route,fill='#C6D8CE',width=max(1,round(3*sx)))
    lengths=[math.dist(a,b) for a,b in zip(route,route[1:])]
    remaining=sum(lengths)*q
    points=[route[0]]
    for a,b,length in zip(route,route[1:],lengths):
        fraction=min(1,max(0,remaining/max(length,1)))
        points.append((round(a[0]+(b[0]-a[0])*fraction),round(a[1]+(b[1]-a[1])*fraction)))
        remaining-=length
        if fraction<1: break
    d.line(points,fill=accent,width=max(2,round(7*sx)))
    tip=points[-1]; r=max(2,round(10*sx))
    d.ellipse((tip[0]-r,tip[1]-r,tip[0]+r,tip[1]+r),fill=accent)
    for obj in states(scene,frame):
        x,y,size=obj['x'],obj['y'],obj['size']
        box=rect((x-size/2,y-size/2,x+size/2,y+size/2)); shapes.append(box)
        material=p.get('material','flat')
        if obj['id']==1:
            shadow=[box[0]+round(12*sx),box[1]+round(15*sy),box[2]+round(12*sx),box[3]+round(15*sy)]
            d.rounded_rectangle(shadow,radius=round(32*sx),fill='#D5E3D9')
            fill='#FFFFFF' if material!='glass' else '#DEEEE8'
            radius=28 if strategy!='fold' else 6+obj['progress']*38
            d.rounded_rectangle(box,radius=round(radius*sx),fill=fill,outline=accent,width=max(2,round(4*sx)))
            if material=='paper':
                rng=random.Random(scene['seed'])
                for _ in range(750):
                    px=rng.randint(box[0]+12,box[2]-12); py=rng.randint(box[1]+12,box[3]-12)
                    d.point((px,py),fill='#DDE6DC')
            elif material=='glass':
                d.line((box[0]+20,box[1]+20,box[2]-20,box[1]+20),fill='white',width=max(1,round(4*sy)))
            # Transformation grows out of the existing route; it never swaps a template scene.
            transition=p.get('transition','carry')
            turn=obj['progress']
            if transition=='grow':
                bar=max(1,round((size-72)*sx*turn))
                d.rounded_rectangle((box[0]+round(36*sx),round((y-8)*sy),box[0]+round(36*sx)+bar,round((y+8)*sy)),radius=max(1,round(8*sx)),fill=accent)
            elif transition=='ribbon':
                pts=[(round((x-size/2+30+j/40*(size-60))*sx),round((y+25*math.sin(j/40*math.pi*2)*turn)*sy)) for j in range(41)]
                d.line(pts,fill=accent,width=max(2,round(8*sx)))
            elif strategy=='constellation':
                verts=[(round((x+60*math.cos(a))*sx),round((y+60*math.sin(a))*sy)) for a in (0,2.1,4.2,0)]
                d.line(verts,fill=accent,width=max(1,round(4*sx)))
                for vx,vy in verts[:3]:
                    rr=max(3,round(10*sx));d.ellipse((vx-rr,vy-rr,vx+rr,vy+rr),fill=accent)
            elif strategy=='fold':
                d.polygon([tuple(rect((x-65,y-45,x,y))[0:2]),(round((x+70)*sx),round((y-35)*sy)),(round((x-5)*sx),round((y+65)*sy))],fill=accent)
            else:
                pts=[(round((x-80)*sx),round((y+35)*sy)),(round((x-25)*sx),round((y-30)*sy)),(round((x+40)*sx),round((y+10)*sy)),(round((x+85)*sx),round((y-45)*sy))]
                d.line(pts,fill=accent,width=max(2,round(8*sx)))
            text(x,y+100,'DIRECTION',label,accent,'mm')
        else:
            d.ellipse(box,outline=accent,width=max(2,round(4*sx)),fill=bg)
            text(x,y,'IN' if obj['id']==0 else 'OUT',label,accent,'mm')
    text(150,950,'ORIGINAL STUDY · NO CLIENT CLAIMS',font,accent)
    text(1765,950,'03 SEC',font,accent,'ra')
    return im,{'frame':frame,'states':states(scene,frame),'text_bounds':boxes,'shape_bounds':shapes,
               'style':{'background':bg,'ink':ink,'accent':accent,'primary_object':1,'strategy':strategy,
                        'material':p.get('material','flat'),'transition':p.get('transition','carry')}}

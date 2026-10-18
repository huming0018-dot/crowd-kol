"""Retain Vision rectangles and project their visible intersection into video space."""
import math

POLICY='crop_image_unit_square_intersection'

def project(raw,crop_top,crop_bottom):
    if not isinstance(raw,list) or len(raw)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) for x in raw):raise ValueError('invalid_video_ocr_native')
    x,y,width,height=raw
    if not -1<=x<=2 or not -1<=y<=2 or not 0<width<=3 or not 0<height<=3:raise ValueError('invalid_video_ocr_native')
    left,bottom=max(0,x),max(0,y);right,top=min(1,x+width),min(1,y+height)
    if right<=left or top<=bottom:raise ValueError('invalid_video_ocr_native')
    scale=crop_bottom-crop_top
    return {'native_bbox':list(raw),'intersection_policy':POLICY,
            'bbox':[left,crop_top+scale*(1-top),right-left,scale*(top-bottom)]}

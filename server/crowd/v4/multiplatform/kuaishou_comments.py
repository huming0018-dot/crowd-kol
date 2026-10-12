"""Preserve root-thread relations from the existing successful comment response."""
from contextvars import ContextVar
import re

RELATIONS = ContextVar('crowd_ks_comment_relations',default=None)
ROOT = 'reported_root_endpoint'
REPLY = 'reported_subcomment_root_scope'


def identity(value,photo=False):
    if type(value) not in (int,str):return None
    value=str(value)
    pattern=r'[A-Za-z0-9_-]{1,200}' if photo else r'[1-9][0-9]{0,29}'
    return value if re.fullmatch(pattern,value) else None


def relations(payload,photo_id,parent=None):
    photo_id=identity(photo_id,photo=True)
    if not photo_id or not isinstance(payload,dict) or type(payload.get('result')) is not int or payload['result']!=1:return {}
    root=parent is None;parent='0' if root else identity(parent)
    if parent is None:return {}
    rows=payload.get('rootCommentsV2' if root else 'subCommentsV2')
    if not isinstance(rows,list) or len(rows)>2000:return {}
    result={}
    for row in rows:
        if not isinstance(row,dict):continue
        ids=[identity(row[k]) for k in ('comment_id','commentId') if k in row]
        if not ids or None in ids or len(set(ids))!=1:continue
        comment_id=ids[0]
        if not root and comment_id==parent:continue
        # This is the source root-thread scope, not an inferred direct reply-to user.
        result[(photo_id,comment_id)]={'parent_comment_id':parent,'parent_relation_basis':ROOT if root else REPLY}
    return result


def install_hook(client_class,store_factory):
    original_root=client_class.get_video_comments
    original_reply=client_class.get_video_sub_comments
    original_all=client_class.get_video_all_comments
    original_store=store_factory.create_store
    async def root(self,photo_id,*args,**kwargs):
        payload=await original_root(self,photo_id,*args,**kwargs)
        RELATIONS.set(relations(payload,photo_id));return payload
    async def reply(self,photo_id,root_comment_id,*args,**kwargs):
        payload=await original_reply(self,photo_id,root_comment_id,*args,**kwargs)
        RELATIONS.set(relations(payload,photo_id,root_comment_id) if identity(root_comment_id) else {});return payload
    async def all_comments(self,*args,**kwargs):
        token=RELATIONS.set(None)
        try:return await original_all(self,*args,**kwargs)
        finally:RELATIONS.reset(token)
    class Store:
        def __init__(self,store):self.store=store
        def __getattr__(self,name):return getattr(self.store,name)
        async def store_comment(self,comment_item):
            key=(identity(comment_item.get('video_id'),photo=True),identity(comment_item.get('comment_id')))
            relation=(RELATIONS.get() or {}).get(key)
            if relation and 'parent_comment_id' not in comment_item:
                comment_item={**comment_item,**relation}
            return await self.store.store_comment(comment_item=comment_item)
    client_class.get_video_comments=root
    client_class.get_video_sub_comments=reply
    client_class.get_video_all_comments=all_comments
    store_factory.create_store=staticmethod(lambda:Store(original_store()))

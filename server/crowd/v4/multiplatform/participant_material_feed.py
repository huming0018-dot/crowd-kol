"""Read-only central ACK input for the existing durable material worker."""
from pathlib import Path
import os,stat,tempfile
from pro_ack_snapshot import validate_cursor

def fetch(client,root,after):
    from automatic_materials import canonical,sha,validate_context
    from pro_ack_snapshot import validate_group
    if after is not None:validate_cursor(after)
    from cloud_sync import CloudError
    try:page=client.call('participant_pro_receipts',{'after':after,'limit':1})
    except CloudError as error:
        if str(error)!='comment_capture_pending':raise
        # Server has an unsealed original body: retain the exact cursor and retry
        # only this read on a later normal worker tick; no partial context is queued.
        return {'contexts':[],'next_cursor':after,'rescan':False}
    if type(page) is not dict or set(page)!={'schema','groups','next_cursor','has_more'} or page['schema']not in ('crowd-participant-pro-receipt-feed-v1','crowd-participant-pro-receipt-feed-v2') or type(page['groups']) is not list or len(page['groups'])>1 or type(page['has_more']) is not bool:
        raise ValueError('participant_pro_feed_invalid')
    groups=page['groups']; cursor=page['next_cursor']
    for group in groups:validate_group(group);validate_cursor(group['group_cursor'])
    if (groups and cursor!=groups[-1]['group_cursor']) or (not groups and (cursor!=after or page['has_more'])):
        raise ValueError('participant_pro_feed_invalid')
    root=Path(root).absolute();directory=root/'data-products/participant-pro-ack-inputs'
    if any(p.is_symlink() for p in (directory,*directory.parents)):raise ValueError('participant_pro_input_unsafe')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    contexts=[]
    for group in groups:
        blob=canonical(group);digest=sha(blob);path=directory/(digest+'.json')
        if len(blob)>8*1024*1024:raise ValueError('participant_pro_input_too_large')
        def compare_existing():
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as stream:
                meta=os.fstat(stream.fileno())
                if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=os.getuid() or meta.st_mode&0o077 or meta.st_nlink!=1 or stream.read(8*1024*1024+1)!=blob:
                    raise ValueError('participant_pro_input_changed')
        if path.exists() or path.is_symlink():compare_existing()
        else:
            fd,tmp=tempfile.mkstemp(prefix='.pro-ack-',dir=directory)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(blob);stream.flush();os.fsync(stream.fileno())
                try:os.link(tmp,path,follow_symlinks=False)
                except FileExistsError:compare_existing()
            finally:os.unlink(tmp)
            fd=os.open(directory,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        context={'schema':'crowd-participant-pro-material-context-v1',
            **{key:group[key] for key in ('task_id','subject','installation_id','dispatch_id','group_cursor')},
            'group_path':str(path),'group_sha256':digest}
        validate_context(context);contexts.append(context)
    # created_at is transaction start, not commit order. Revisit all scopes
    # after every complete traversal so late commits cannot fall behind a watermark.
    rescan=not groups and after is not None
    return {'contexts':contexts,'next_cursor':None if rescan else cursor,'rescan':rescan}

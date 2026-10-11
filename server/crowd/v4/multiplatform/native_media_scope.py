"""Separate native video media limits from JSON responses and total task limits."""
from contextvars import ContextVar
from urllib.parse import urlsplit

NATIVE_VIDEO_MEDIA_ACTIVE = ContextVar('crowd_native_video_media_active', default=False)
DEFAULT_RESPONSE_BYTES = 25 * 1024 * 1024
NATIVE_VIDEO_MEDIA_BYTES = 64 * 1024 * 1024

def select_douyin_stream(item):
    """Select a complete native rendition before downloading, without probing URLs."""
    if not isinstance(item,dict) or not isinstance(item.get('video'),dict) or item.get('images'):
        return item,None
    video=item['video'];rows=[]
    def number(value):
        return value if type(value) is int and 0<value<=10**12 else None
    def add(address,rate=None):
        if not isinstance(address,dict):return
        raw=address.get('url_list')
        if not isinstance(raw,list):return
        urls=[]
        for value in raw[:3]:
            if not isinstance(value,str) or len(value)>4096:continue
            try:
                u=urlsplit(value)
                host=u.hostname or ''
                if (u.scheme=='https' and not u.username and not u.password and u.port in (None,443)
                        and (host=='www.douyin.com' or host.endswith(('.douyinvod.com','.bytecdn.cn','.ibytedtos.com','.pstatp.com')))):
                    urls.append(value)
            except (TypeError,ValueError):pass
        if not urls:return
        size=number(address.get('data_size'));rate=number(rate)
        rows.append({'address':{**address,'url_list':urls},'size':size,'rate':rate})
    for key in ('play_addr_h264','play_addr_256','play_addr'):add(video.get(key))
    rates=video.get('bit_rate')
    if isinstance(rates,list):
        for row in rates[:32]:
            if isinstance(row,dict):add(row.get('play_addr'),row.get('bit_rate'))
    fitting=[row for row in rows if row['size'] is not None and row['size']<=NATIVE_VIDEO_MEDIA_BYTES]
    unknown=[row for row in rows if row['size'] is None and row['rate'] is not None]
    chosen=min(fitting,key=lambda row:row['size']) if fitting else min(unknown,key=lambda row:row['rate']) if unknown else None
    summary={'strategy':'native_complete_rendition_under_limit','source':'same_native_aweme_detail',
             'candidate_count':len(rows),'fitting_candidate_count':len(fitting),
             'single_file_limit_bytes':NATIVE_VIDEO_MEDIA_BYTES,
             'selection_status':'selected' if chosen else 'no_fitting_reported_rendition',
             'reported_bytes':chosen['size'] if chosen else None,
             'reported_bitrate':chosen['rate'] if chosen else None}
    if chosen is None:return item,summary
    # The installed SDK prioritizes these fields; keep the original detail and cover intact.
    return {**item,'video':{**video,'play_addr_h264':chosen['address'],
                           'play_addr_256':chosen['address'],'play_addr':chosen['address']}},summary


def response_limit(platform):
    if platform in ('dy', 'ks') and NATIVE_VIDEO_MEDIA_ACTIVE.get():
        return NATIVE_VIDEO_MEDIA_BYTES
    return DEFAULT_RESPONSE_BYTES


def install_hook(crawler, platform, output, limit_exception, read, write):
    original = crawler.download_media

    async def bounded_media(self, *args, **kwargs):
        folder = output / platform / 'media'
        previous_parts = set(folder.rglob('*.part')) if folder.exists() else set()
        token = NATIVE_VIDEO_MEDIA_ACTIVE.set(True)
        try:
            if platform=='dy':
                source=kwargs.get('aweme_item') if 'aweme_item' in kwargs else args[0] if args else None
                selected,selection=select_douyin_stream(source)
                if selection is not None:
                    phase=output.parent/'phase.json';previous=read(phase) if phase.exists() else {}
                    write(phase,{**previous,'media_video_selection':selection})
                    if 'aweme_item' in kwargs:kwargs={**kwargs,'aweme_item':selected}
                    elif args:args=(selected,*args[1:])
            return await original(self, *args, **kwargs)
        except limit_exception:
            # A single oversized media file must not abort the remaining comments.
            for path in set(folder.rglob('*.part')) - previous_parts:
                path.unlink(missing_ok=True)
            phase = output.parent / 'phase.json'
            previous = read(phase) if phase.exists() else {}
            write(phase, {**previous, 'media_status': 'limited',
                          'media_reason': 'single_response_byte_limit',
                          'media_single_file_limit_bytes': NATIVE_VIDEO_MEDIA_BYTES})
        finally:
            NATIVE_VIDEO_MEDIA_ACTIVE.reset(token)

    crawler.download_media = bounded_media

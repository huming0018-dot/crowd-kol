"""Separate native video media limits from JSON responses and total task limits."""
from contextvars import ContextVar

NATIVE_VIDEO_MEDIA_ACTIVE = ContextVar('crowd_native_video_media_active', default=False)
DEFAULT_RESPONSE_BYTES = 25 * 1024 * 1024
NATIVE_VIDEO_MEDIA_BYTES = 64 * 1024 * 1024


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

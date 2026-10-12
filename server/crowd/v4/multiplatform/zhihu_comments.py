"""Process-only bounded comment sampling through the installed Zhihu SDK."""
import asyncio
import re


def install_hook(client_class, max_comments, replies, observer=None):
    if type(max_comments) is not int or not 0 <= max_comments <= 200 or type(replies) is not bool:
        raise ValueError('invalid_zhihu_comment_limit')

    async def bounded(self, content, crawl_interval=1.0, callback=None):
        roots, seen = [], set()
        info = {'schema': 'crowd_zhihu_comment_sample_v1', 'coverage': 'bounded_comment_sample',
                'root_limit': max_comments, 'reply_limit': max_comments if replies else 0,
                'roots': 0, 'replies': 0, 'root_pages': 0, 'reply_pages': 0,
                'source_complete': False}

        async def page_rows(parent, remaining, offset):
            if parent is None:
                info['root_pages'] += 1
                response = await self.get_root_comments(content.content_id, content.content_type, offset, min(10, remaining))
            else:
                info['reply_pages'] += 1
                response = await self.get_child_comments(parent.comment_id, offset, min(10, remaining))
            if not isinstance(response, dict) or not isinstance(response.get('data'), list):
                raise ValueError('invalid_zhihu_comment_response')
            rows = self._extractor.extract_comments(content, response['data'])
            accepted = []
            for row in rows:
                identity = getattr(row, 'comment_id', None)
                if not isinstance(identity, str) or not re.fullmatch(r'[1-9][0-9]{0,29}', identity) or identity in seen:
                    continue
                accepted.append(row)
                seen.add(identity)
                if len(accepted) == remaining:
                    break
            paging = response.get('paging', {})
            if not isinstance(paging, dict):
                paging = {}
            next_offset = self._extractor.extract_offset(paging)
            return accepted, next_offset, paging.get('is_end') is True

        try:
            offset = ''
            while len(roots) < max_comments and info['root_pages'] < max_comments:
                rows, next_offset, ended = await page_rows(None, max_comments - len(roots), offset)
                if not rows:
                    break
                if callback:
                    await callback(rows)
                roots.extend(rows)
                info['roots'] = len(roots)
                if ended or not next_offset or next_offset == offset:
                    break
                offset = next_offset
                if len(roots) < max_comments:
                    await asyncio.sleep(crawl_interval)
            if replies:
                for parent in roots:
                    if info['replies'] >= max_comments or info['reply_pages'] >= max_comments:
                        break
                    count = getattr(parent, 'sub_comment_count', 0)
                    if type(count) is not int or count <= 0:
                        continue
                    offset = ''
                    while info['replies'] < max_comments and info['reply_pages'] < max_comments:
                        rows, next_offset, ended = await page_rows(parent, max_comments - info['replies'], offset)
                        if not rows:
                            break
                        if callback:
                            await callback(rows)
                        info['replies'] += len(rows)
                        if ended or not next_offset or next_offset == offset:
                            break
                        offset = next_offset
                        if info['replies'] < max_comments:
                            await asyncio.sleep(crawl_interval)
            return roots
        finally:
            if observer:
                try:
                    observer(info)
                except Exception:
                    pass

    client_class.get_note_all_comments = bounded

"""Local proof that selected Bili detail records belong to the requested video."""
import re
from urllib.parse import urlsplit


def bili_identifier(value):
    if not isinstance(value, str):
        return None
    if re.fullmatch(r'BV[A-Za-z0-9]{10}', value):
        return ('bvid', value)
    if re.fullmatch(r'(?:av)?[0-9]{1,20}', value) and int(value.removeprefix('av')) > 0:
        return ('aid', str(int(value.removeprefix('av'))))
    try:
        url = urlsplit(value)
        if (url.scheme == 'https' and url.hostname in ('bilibili.com', 'www.bilibili.com', 'm.bilibili.com')
                and not url.username and not url.password and not url.port):
            match = re.fullmatch(r'/video/((?:BV[A-Za-z0-9]{10})|(?:av[0-9]{1,20}))/?', url.path)
            if match:
                return bili_identifier(match.group(1))
    except ValueError:
        pass
    return None


def _aliases(row):
    values = [row.get('content_id'), row.get('url')]
    fields = row.get('platform_fields') or {}
    if not isinstance(fields, dict):
        raise ValueError('existing_saved_target_unverified')
    for name in ('bvid', 'aid', 'video_id'):
        if fields.get(name) not in (None, ''):
            value = str(fields[name]) if type(fields[name]) is int else fields[name]
            if bili_identifier(value) is None:
                raise ValueError('existing_saved_target_unverified')
            values.append(value)
    values.append(fields.get('video_url'))
    return {identity for value in values if (identity := bili_identifier(value))}


def validate_existing_targets(lease, records, store=None):
    """Check explicit metadata only; no title inference, BV arithmetic or network."""
    if lease.get('platform') != 'bili':
        return
    request = lease.get('request') or {}
    if request.get('mode') in ('search', 'creator', 'homefeed', 'trending'):
        return
    targets = request.get('targets')
    if request.get('mode') != 'detail' or not isinstance(targets, list) or not 1 <= len(targets) <= 10:
        raise ValueError('existing_saved_target_unverified')
    requested = {bili_identifier(value) for value in targets}
    if None in requested or not isinstance(records, list) or not records:
        raise ValueError('existing_saved_target_unverified')
    grouped = {}
    for item in records:
        row = item.get('record', item) if isinstance(item, dict) else None
        if (not isinstance(row, dict) or row.get('platform') != 'bilibili'
                or row.get('kind') not in ('content', 'comment', 'media')
                or not isinstance(row.get('content_id'), str) or not row['content_id']):
            raise ValueError('existing_saved_target_unverified')
        grouped.setdefault(row['content_id'], []).append(row)
    for content_id, rows in grouped.items():
        aliases = set().union(*(_aliases(row) for row in rows))
        if not any(row.get('kind') == 'content' for row in rows) and store is not None:
            # Comment-only selection may use the locally stored body's explicit
            # aid/BV mapping. It never makes that unselected body a delivery row.
            bodies = store.list_results(filters={'platform':'bilibili', 'content_id':content_id,
                                                 'kind':'content'}, limit=200)['items']
            for body in bodies:
                aliases.update(_aliases(body))
        for kind in ('bvid', 'aid'):
            if len({value for key,value in aliases if key == kind}) > 1:
                raise ValueError('existing_saved_target_mismatch')
        if not requested & aliases:
            known_kind = {kind for kind,_ in aliases}
            code = 'existing_saved_target_mismatch' if any(kind in known_kind for kind,_ in requested) else 'existing_saved_target_unverified'
            raise ValueError(code)

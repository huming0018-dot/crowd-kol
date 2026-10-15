"""Private image delivery; source capture and receipt are reconciled before upload."""
import hashlib
import json
import os
import sqlite3
import stat
import urllib.error
import urllib.request
from pathlib import Path

from analysis_artifact import _safe_ancestors
from cloud_sync import CloudError, SCHEMA, _hash, _strict_json, canonical
from image_cloud import (LIMIT, prepare_image, validate_manifest, verify_receipt,
                         verify_retrieved, signed_url)
from image_cloud import uid as valid_uuid
from mc_runner import write
from media_cloud import _job_lock, _receipt_folder, _url, NoRedirect
from saved_media_attachments import verify_source


def uid(value):
    if not valid_uuid(value):
        raise ValueError('image_cloud_identity_mismatch')
    return value


def object_file(path, limit):
    _safe_ancestors(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid() or before.st_size > limit:
            raise ValueError('image_cloud_identity_mismatch')
        data = bytearray()
        while len(data) <= limit:
            block = os.read(fd, min(65536, limit + 1 - len(data)))
            if not block: break
            data.extend(block)
        after = os.fstat(fd)
        if len(data) > limit or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('image_cloud_identity_mismatch')
        try: value = _strict_json(bytes(data))
        except (ValueError, RecursionError): raise ValueError('image_cloud_identity_mismatch') from None
        if not isinstance(value, dict): raise ValueError('image_cloud_identity_mismatch')
        return value
    finally: os.close(fd)


def reply(value):
    if not isinstance(value, dict): raise ValueError('image_receipt_mismatch')
    return value


def source_capture(outbox_path, adapter, run_id, virtual_path, client):
    if client is None or getattr(client, 'role', None) not in ('owner', 'worker'):
        raise ValueError('cloud_configuration_required')
    asset = adapter.resolve(run_id, virtual_path)
    sidecar = object_file(asset.parent / 'attachment.json', 1024 * 1024)
    _, body, _ = verify_source(adapter._run(run_id), sidecar['media_id'])
    path = Path(outbox_path)
    _safe_ancestors(path)
    if not path.is_file():
        raise ValueError('image_capture_not_received')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute("SELECT id,envelope,digest,receipt FROM captures WHERE state='acknowledged' "
                          "AND json_valid(envelope) AND json_extract(envelope,'$.record.origin.run_id')=? "
                          "AND json_extract(envelope,'$.record.kind')=? "
                          "AND json_extract(envelope,'$.record.content_id')=? LIMIT 101",
                          (run_id, body['kind'], body['content_id'])).fetchall()
    if len(rows) > 100:
        raise ValueError('image_capture_ambiguous')
    matches = []
    for capture_id, encoded, digest, saved_receipt in rows:
        try:
            envelope, receipt = _strict_json(encoded), _strict_json(saved_receipt)
            if not isinstance(envelope, dict) or not isinstance(receipt, dict) or not isinstance(envelope.get('record'), dict):
                raise ValueError()
            fields = {'schema', 'capture_id', 'task_id', 'child_id', 'run_id', 'lease_epoch',
                      'platform', 'delivery_basis', 'source_kind', 'adapter_version',
                      'normalizer_version', 'record', 'packaged_at'}
            if (set(envelope) != fields or envelope.get('schema') != SCHEMA
                    or envelope.get('platform') != body['platform']
                    or envelope.get('source_kind') != 'machine_api'
                    or envelope.get('adapter_version') != 'cloud-machine-v1'
                    or envelope.get('normalizer_version') != 'mc-normalized-v2'
                    or envelope.get('delivery_basis') not in ('live_capture', 'existing_saved')
                    or not isinstance(envelope.get('packaged_at'), str)
                    or canonical(envelope) != encoded or _hash(SCHEMA, envelope) != digest
                    or envelope.get('capture_id') != capture_id):
                raise ValueError()
            if envelope['record'].get('comment_id') != body.get('comment_id'):
                continue
            expected = {k: envelope[k] for k in ('task_id', 'child_id', 'run_id', 'lease_epoch')}
            expected.update(capture_id=capture_id, envelope_hash=digest, status='received', reward_eligible=False, source_kind='machine_api')
            if type(envelope['lease_epoch']) is not int or any(canonical(receipt.get(k)) != canonical(v) for k, v in expected.items()):
                raise ValueError()
            candidate = {'record': envelope['record'], 'receipt': receipt}
            prepare_image(adapter, run_id, virtual_path, candidate)
            matches.append(candidate)
        except (KeyError, TypeError, ValueError, RecursionError):
            raise ValueError('image_capture_binding_changed') from None
    if len(matches) != 1:
        raise ValueError('image_capture_ambiguous' if matches else 'image_capture_not_received')
    selected = matches[0]
    saved = selected['receipt']
    if client.role == 'owner':
        response = reply(client.call('results', {'task_id': saved['task_id']}))
        if not isinstance(response.get('items'), list): raise ValueError('image_capture_binding_changed')
        items = [x for x in response['items'] if isinstance(x, dict)
                 and isinstance(x.get('receipt'), dict) and x['receipt'].get('capture_id') == saved['capture_id']]
        if len(items) != 1 or canonical(items[0].get('record')) != canonical(selected['record']):
            raise ValueError('image_capture_binding_changed')
        fresh = items[0].get('receipt')
    else:
        response = reply(client.call('receipt', {k: saved[k] for k in ('run_id', 'lease_epoch', 'capture_id', 'envelope_hash')}))
        fresh = response.get('receipt')
    if not isinstance(fresh, dict) or any(canonical(fresh.get(k)) != canonical(saved.get(k))
            for k in ('task_id', 'child_id', 'run_id', 'lease_epoch', 'capture_id', 'envelope_hash', 'status', 'reward_eligible', 'source_kind')):
        raise ValueError('image_capture_binding_changed')
    return {'record': selected['record'], 'receipt': fresh}


def prepare(jobs, adapter, outbox_path, client, run_id, virtual_path):
    capture = source_capture(outbox_path, adapter, run_id, virtual_path, client)
    return prepare_image(adapter, run_id, virtual_path, capture)


def _journal(jobs, client, manifest):
    path = _receipt_folder(jobs) / (uid(manifest['local_job_id']) + '.json')
    _safe_ancestors(path)
    endpoint_hash = hashlib.sha256(client.endpoint.encode()).hexdigest()
    value = {'manifest': manifest, 'attempted': False, 'endpoint_sha256': endpoint_hash}
    if path.exists():
        saved = object_file(path, 300000)
        allowed = {'manifest', 'attempted', 'endpoint_sha256', 'artifact_id', 'state', 'receipt'}
        if (set(saved) - allowed or type(saved.get('attempted')) is not bool
                or not isinstance(saved.get('manifest'), dict)
                or saved.get('endpoint_sha256') != endpoint_hash or canonical(saved['manifest']) != canonical(manifest)):
            raise ValueError('image_cloud_identity_mismatch')
        if 'artifact_id' in saved: uid(saved['artifact_id'])
        if saved.get('state') not in ('uploading', 'received') or 'artifact_id' not in saved:
            raise ValueError('image_cloud_identity_mismatch')
        if saved['state'] == 'uploading' and saved['attempted'] is not True: raise ValueError('image_cloud_identity_mismatch')
        if saved['state'] == 'received': verify_receipt(saved.get('receipt'), manifest)
        value = saved
    return path, value


def publish(jobs, adapter, outbox_path, client, run_id, virtual_path, opener=None):
    manifest, data = prepare(jobs, adapter, outbox_path, client, run_id, virtual_path)
    with _job_lock(jobs, manifest['local_job_id']):
        path, journal = _journal(jobs, client, manifest)
        prepared = reply(client.call('image_prepare', manifest))
        artifact_id = uid(prepared.get('artifact_id'))
        if prepared.get('manifest_hash') != validate_manifest(manifest)['manifest_hash']:
            raise ValueError('image_receipt_mismatch')
        if journal.get('artifact_id', artifact_id) != artifact_id:
            raise ValueError('image_cloud_identity_mismatch')
        try:
            completed = client.call('image_commit', {'artifact_id': artifact_id})
        except CloudError as error:
            if str(error) != 'image_object_missing':
                raise
            if journal.get('attempted') is not False:
                raise ValueError('image_upload_outcome_unknown') from None
            suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}[manifest['content_mime']]
            storage = {'bucket_id': 'crowd-machine-media', 'object_path':
                       'crowd-owner-main/' + artifact_id + '/' + manifest['asset_sha256'] + suffix}
            url = _url(client, prepared.get('upload_url'), 'upload/sign', storage)
            journal.update(artifact_id=artifact_id, attempted=True, state='uploading')
            write(path, journal)
            request = urllib.request.Request(url, data=data, method='PUT', headers={
                'Content-Type': manifest['content_mime'], 'Content-Length': str(len(data)), 'x-upsert': 'false'})
            opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            try:
                with opener.open(request, timeout=60) as response:
                    if response.status not in (200, 201):
                        raise ValueError('image_upload_outcome_unknown')
                    response.read(10000)
            except (OSError, ValueError, urllib.error.URLError):
                try:
                    completed = client.call('image_commit', {'artifact_id': artifact_id})
                except Exception:
                    raise ValueError('image_upload_outcome_unknown') from None
            else:
                completed = client.call('image_commit', {'artifact_id': artifact_id})
        receipt = verify_receipt(reply(completed).get('receipt'), manifest)
        write(path, {**journal, 'artifact_id': artifact_id, 'state': 'received', 'receipt': receipt})
        return {'ok': True, 'state': 'received', 'receipt': receipt, 'source_requests': 0, 'model_calls': 0}


def status(jobs, adapter, outbox_path, client, run_id, virtual_path):
    manifest, _ = prepare(jobs, adapter, outbox_path, client, run_id, virtual_path)
    _, journal = _journal(jobs, client, manifest)
    if not journal.get('artifact_id'):
        return {'state': 'not_saved', 'receipt': None}
    response = reply(client.call('image_get', {'artifact_id': uid(journal['artifact_id'])}))
    receipt = verify_receipt(response.get('receipt'), manifest)
    return {'state': 'received', 'receipt': receipt}


def download(jobs, adapter, outbox_path, client, run_id, virtual_path, opener=None):
    manifest, _ = prepare(jobs, adapter, outbox_path, client, run_id, virtual_path)
    _, journal = _journal(jobs, client, manifest)
    if not journal.get('artifact_id'):
        raise ValueError('image_cloud_not_saved')
    response = reply(client.call('image_get', {'artifact_id': uid(journal['artifact_id'])}))
    receipt = verify_receipt(response.get('receipt'), manifest)
    url = signed_url(client.endpoint, response.get('download_url'), receipt, manifest)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers={'Accept': manifest['content_mime']}), timeout=60) as stream:
            if stream.status != 200 or stream.headers.get('Content-Range'):
                raise ValueError('image_cloud_download_mismatch')
            data = stream.read(LIMIT + 1)
    except (OSError, urllib.error.URLError):
        raise ValueError('image_cloud_download_failed') from None
    verify_retrieved(data, receipt, manifest)
    return {'data': data, 'mime': manifest['content_mime'], 'sha256': manifest['asset_sha256'], 'receipt': receipt}

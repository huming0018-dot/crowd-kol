"""Owner host adapter: read-only preview, explicit decision, never release/pin."""
from pathlib import Path
import hashlib
import importlib.util
import json
import secrets
import time
import re
import os
import fcntl
import stat
from owner_knowledge_binding import OwnerKnowledgeBinding, BindingError, canonical, protected_bytes, sync_directory
from material_bridge import read_bytes

CONFIG_KEYS = {'binding_config', 'binding_sha256', 'preview_config', 'preview_config_sha256',
               'preview_helper', 'preview_helper_sha256'}
DECISION_KEYS = {'decision', 'reason', 'expected_candidate_hash', 'intent_id', 'preview_token'}


class OwnerKnowledgeService:
    def __init__(self, service_config, service_sha256, owner_client):
        raw = protected_bytes(service_config)
        if hashlib.sha256(raw).hexdigest() != service_sha256:
            raise BindingError('knowledge_service_config_changed')
        config = json.loads(raw)
        if type(config) is not dict or set(config) != CONFIG_KEYS:
            raise BindingError('knowledge_service_config_invalid')
        self.config, self.client = config, owner_client
        self.config_path, self.config_sha256 = service_config, service_sha256
        self.binding = OwnerKnowledgeBinding(config['binding_config'], config['binding_sha256'])
        self.previews = {}

    def _check_config(self):
        if hashlib.sha256(protected_bytes(self.config_path)).hexdigest() != self.config_sha256:
            raise BindingError('knowledge_service_config_changed')

    def _preview_path(self, token):
        if type(token) is not str or re.fullmatch(r'[A-Za-z0-9_-]{40,64}', token) is None:
            raise BindingError('knowledge_preview_required')
        parent = Path(self.binding.config['intents'])
        parent.mkdir(mode=0o700, exist_ok=True)
        directory = parent / ('previews-' + self.config_sha256)
        directory.mkdir(mode=0o700, exist_ok=True)
        if (directory.is_symlink() or parent.is_symlink()
                or directory.stat().st_mode & 0o077 or parent.stat().st_mode & 0o077):
            raise BindingError('knowledge_preview_directory_invalid')
        return directory / (hashlib.sha256(token.encode()).hexdigest() + '.json')

    def _save_preview(self, token, value):
        path = self._preview_path(token)
        temporary = path.with_suffix('.' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)

    def _get_preview(self, token):
        # Disk is authoritative across separate 065 request processes.
        try:
            value = json.loads(protected_bytes(self._preview_path(token)))
        except FileNotFoundError:
            raise BindingError('knowledge_preview_required') from None
        self.previews[token] = value
        return value

    def preview(self):
        self._check_config()
        principal = self.binding.authenticate(self.client)
        config = self.config
        helper_path = Path(config['preview_helper'])
        # Verified own helper source, not caller-controlled import/plugin code.
        raw = read_bytes(helper_path, 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != config['preview_helper_sha256']:
            raise BindingError('knowledge_preview_helper_changed')
        spec = importlib.util.spec_from_loader('fixed_knowledge_preview', loader=None)
        helper = importlib.util.module_from_spec(spec)
        helper.__file__ = str(helper_path)
        exec(compile(raw, str(helper_path), 'exec'), helper.__dict__)
        config_raw = protected_bytes(config['preview_config'])
        if hashlib.sha256(config_raw).hexdigest() != config['preview_config_sha256']:
            raise BindingError('knowledge_preview_config_changed')
        preview_config = json.loads(config_raw)
        data = helper.preview(preview_config)
        if (data['proposal_id'] != self.binding.config['proposal_id']
                or data['candidate_hash'] != self.binding.config['candidate_hash']):
            raise BindingError('knowledge_preview_binding_changed')
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.previews = {k: v for k, v in self.previews.items() if now - v['created'] < 300}
        directory = self._preview_path(token).parent
        active = 0
        for path in directory.iterdir():
            if re.fullmatch(r'[a-f0-9]{64}\.json', path.name) is None:
                continue
            previous = json.loads(protected_bytes(path))
            if not 0 <= now - previous['created'] < 300:
                path.unlink()  # Only this service's expired private preview tokens.
            else:
                active += 1
        sync_directory(directory)
        if active >= 32:
            raise BindingError('knowledge_preview_capacity')
        self.previews[token] = {'created': now, 'candidate_hash': data['candidate_hash'],
                                'fingerprint': hashlib.sha256(canonical(data)).hexdigest(),
                                'intent_id': None}
        self._save_preview(token, self.previews[token])
        unresolved = self.binding.unresolved_decisions()
        reviewable = not unresolved and data.get('proposal_status', 'proposed') == 'proposed'
        return {**data, 'review_scope': list(self.binding.config['scope']), 'preview_token': token, 'preview_fingerprint': self.previews[token]['fingerprint'],
                'principal_kind': principal['kind'], 'human_uid': None,
                'role_state': {**data['role_state'], 'central_owner_service_scope_bound': True},
                'unresolved_decisions': unresolved,
                'decision_available': reviewable,
                'actions': {x: {'enabled': reviewable} for x in ('approved', 'request_changes', 'rejected')},
                'notice': '原审核决定结果待核对，新的审核已暂停；请先核对原决定。' if unresolved else '本次仅记录知识审核决定。发布与结果生效另行处理，不会自动采集或更新评分。' if reviewable else '原提案已有审核状态，请查看原决定与发布记录；不会自动再次审核或更新评分。'}

    def decide(self, payload):
        self._check_config()
        if type(payload) is not dict or set(payload) != DECISION_KEYS:
            raise BindingError('knowledge_decision_request_invalid')
        self.binding.validate_decision(**{k: v for k, v in payload.items() if k != 'preview_token'})
        token = payload['preview_token']
        if type(token) is not str:
            raise BindingError('knowledge_preview_required')
        self._get_preview(token)  # Reject unknown token before creating its lock.
        lock = self._preview_path(token).with_suffix('.lock')
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BindingError('knowledge_preview_lock_invalid')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BindingError('knowledge_decision_in_progress') from None
            return self._decide_locked(payload)
        finally:
            os.close(fd)

    def _decide_locked(self, payload):
        token = payload['preview_token']
        preview = self._get_preview(token)
        if not 0 <= time.time() - preview['created'] < 300:
            raise BindingError('knowledge_preview_expired')
        if payload['expected_candidate_hash'] != preview['candidate_hash']:
            raise BindingError('knowledge_candidate_changed')
        if preview['intent_id'] not in (None, payload['intent_id']):
            raise BindingError('knowledge_preview_already_submitted')
        # Mark before writes; errors retain the original intent and never auto-retry.
        preview['intent_id'] = payload['intent_id']
        self._save_preview(token, preview)
        result = self.binding.decide(self.client, **{k: v for k, v in payload.items() if k != 'preview_token'})
        return self._result(result, payload['intent_id'])

    def _result(self, result, intent_id):
        status = result['decision']['status']
        return {'state': status, 'decision_id': result['decision']['decision_id'],
                'proposal_id': result['decision']['proposal_id'], 'intent_id': intent_id,
                'knowledge_released': False, 'consumer_pin_changed': False,
                'human_uid': None, 'principal_kind': result['principal']['kind'],
                'message': {'accepted': '提案已批准，尚未发布生效。', 'rejected': '提案已不采用，现有结果保持。',
                            'review': '提案已退回修改，现有结果保持。'}[status]}

    def status(self, payload):
        self._check_config()
        if (type(payload) is not dict or set(payload) != {'intent_id'}
                or type(payload['intent_id']) is not str
                or re.fullmatch(r'[a-f0-9-]{36}', payload['intent_id']) is None):
            raise BindingError('knowledge_status_request_invalid')
        self.binding.authenticate(self.client)
        path = Path(self.binding.config['intents']) / (payload['intent_id'] + '.json')
        try:
            intent = json.loads(protected_bytes(path))
        except FileNotFoundError:
            return {'state': 'not_found', 'intent_id': payload['intent_id'],
                    'message': '尚未找到原决定记录；请核对原请求，不会自动重发。'}
        if intent['state'] != 'completed':
            return {'state': 'outcome_unknown', 'intent_id': payload['intent_id'],
                    'message': '原决定结果尚待核对，请保留此记录；不会自动再次审核。'}
        result = intent['result']
        if (result['decision']['proposal_id'] != self.binding.config['proposal_id']
                or result['principal']['binding_sha256'] != self.binding.config_sha256):
            raise BindingError('knowledge_status_binding_changed')
        return self._result(result, payload['intent_id'])

    def request(self, body):
        if type(body) is not dict or set(body) != {'action', 'payload'}:
            raise BindingError('knowledge_request_invalid')
        if body['action'] == 'preview' and body['payload'] == {}:
            return self.preview()
        if body['action'] == 'decide':
            return self.decide(body['payload'])
        if body['action'] == 'status':
            return self.status(body['payload'])
        raise BindingError('knowledge_action_denied')


def main():
    import argparse
    from cloud_sync import CloudClient
    parser = argparse.ArgumentParser()
    parser.add_argument('--service-config', required=True)
    parser.add_argument('--service-sha256', required=True)
    parser.add_argument('--cloud-config', required=True)
    parser.add_argument('--body-fd', type=int, required=True)
    args = parser.parse_args()
    try:
        parts, length = [], 0
        while True:
            chunk = os.read(args.body_fd, min(4096, 32769 - length))
            if not chunk:
                break
            parts.append(chunk); length += len(chunk)
            if length > 32768:
                raise BindingError('knowledge_request_too_large')
        raw = b''.join(parts)
        service = OwnerKnowledgeService(args.service_config, args.service_sha256,
                                        CloudClient(args.cloud_config, role='owner'))
        result = service.request(json.loads(raw))
        print(canonical(result).decode())
        return 0
    except BindingError as error:
        print(canonical({'error': str(error)}).decode())
        return 2
    except Exception:
        print(canonical({'error': 'knowledge_service_unavailable'}).decode())
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

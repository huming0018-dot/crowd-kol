"""Fixed backend service binding, not browser role parsing or human approval.

Host must enforce its Owner session/Origin/CSRF before invoking decide().
This module never releases knowledge or changes a consumer publication.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import tempfile
import yaml
from toolbox.knowledge import AuthContext, KnowledgeStore, _candidate_hash
from material_bridge import read_bytes

OWNER_SCOPE = 'crowd-owner-main'
KEYS = {'schema', 'endpoint', 'owner_scope', 'scope', 'authorization_ref',
        'workspace', 'candidate', 'proposal_id', 'candidate_hash', 'intents',
        'target_version', 'manager_actor', 'reviewer_actor'}


class BindingError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def protected_bytes(path, limit=65536):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise BindingError('knowledge_binding_path_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & 0o077
                or not 0 < before.st_size <= limit):
            raise BindingError('knowledge_binding_requires_0600')
        data = os.read(fd, limit + 1)
        after = os.fstat(fd)
        if len(data) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise BindingError('knowledge_binding_changed')
        return data
    finally:
        os.close(fd)


class OwnerKnowledgeBinding:
    def __init__(self, config_path, config_sha256):
        raw = protected_bytes(config_path)
        if hashlib.sha256(raw).hexdigest() != config_sha256:
            raise BindingError('knowledge_binding_changed')
        config = json.loads(raw)
        if (type(config) is not dict or set(config) != KEYS
                or config['schema'] != 'crowd-owner-knowledge-binding-v1'
                or config['owner_scope'] != OWNER_SCOPE
                or type(config['scope']) is not list or len(config['scope']) != 3
                or any(type(x) is not str or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', x) is None for x in config['scope'])
                or not isinstance(config['authorization_ref'], str) or not config['authorization_ref']
                or re.fullmatch(r'https://[a-z0-9]+\.supabase\.co/functions/v1/crowd-machine', config['endpoint']) is None
                or re.fullmatch(r'[a-f0-9]{64}', config['candidate_hash']) is None):
            raise BindingError('knowledge_binding_invalid')
        for key in ('workspace', 'candidate', 'intents'):
            path = Path(config[key])
            if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
                raise BindingError('knowledge_binding_path_invalid')
        if (type(config['proposal_id']) is not str or re.fullmatch(r'prop:[a-zA-Z0-9:_-]{1,150}', config['proposal_id']) is None
                or type(config['target_version']) is not str or re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', config['target_version']) is None
                or any(type(config[k]) is not str or re.fullmatch(r'[a-zA-Z0-9:_-]{1,150}', config[k]) is None for k in ('manager_actor', 'reviewer_actor'))
                or config['manager_actor'] == config['reviewer_actor']):
            raise BindingError('knowledge_binding_proposal_invalid')
        # Reuse the original scope validator; authority comes only from this
        # protected, SHA-pinned backend mapping, never a browser role argument.
        AuthContext(tenant=config['scope'][0], project=config['scope'][1], space=config['scope'][2],
                    role='reviewer', actor_ref=config['reviewer_actor'])
        self.config = config
        self.config_path = config_path
        self.config_sha256 = config_sha256

    def authenticate(self, owner_client):
        # This exact class is constructed by the host from its protected config.
        from cloud_sync import CloudClient
        if (type(owner_client) is not CloudClient or owner_client.role != 'owner'
                or owner_client.endpoint != self.config['endpoint']):
            raise BindingError('knowledge_owner_principal_denied')
        result = owner_client.call('task_list', {})
        if type(result) is not dict:
            raise BindingError('knowledge_owner_principal_denied')
        return {'kind': 'central_owner_service', 'endpoint': owner_client.endpoint,
                'owner_scope': OWNER_SCOPE, 'human_uid': None,
                'binding_sha256': self.config_sha256}

    def _context(self, reviewer=False):
        scope = self.config['scope']
        return AuthContext(tenant=scope[0], project=scope[1], space=scope[2],
                           role='reviewer' if reviewer else 'admin',
                           actor_ref=self.config['reviewer_actor'] if reviewer else self.config['manager_actor'])

    def validate_decision(self, *, decision, reason, expected_candidate_hash, intent_id):
        """Pure request check, also used before reserving a preview token."""
        if (type(decision) is not str or decision not in ('approved', 'rejected', 'request_changes')
                or type(reason) is not str or not 1 <= len(reason) <= 2000 or not reason.strip()
                or type(intent_id) is not str
                or re.fullmatch(r'[a-f0-9-]{36}', intent_id) is None
                or type(expected_candidate_hash) is not str
                or expected_candidate_hash != self.config['candidate_hash']):
            raise BindingError('knowledge_decision_invalid')

    def decide(self, owner_client, *, decision, reason, expected_candidate_hash, intent_id):
        # No caller-provided actor, role, scope, proposal, workspace, or path.
        self.validate_decision(decision=decision, reason=reason,
                               expected_candidate_hash=expected_candidate_hash, intent_id=intent_id)
        if hashlib.sha256(protected_bytes(self.config_path)).hexdigest() != self.config_sha256:
            raise BindingError('knowledge_binding_changed')
        principal = self.authenticate(owner_client)
        config = self.config
        with tempfile.TemporaryDirectory(prefix='knowledge-reviewed-pack-') as scratch:
            candidate = Path(scratch)
            for name in ('pack.yaml', 'fields.yaml', 'pointers.json', 'validation.yaml', 'rubric.yaml', 'expectations.yaml'):
                (candidate / name).write_bytes(read_bytes(Path(config['candidate']) / name, 8 * 1024 * 1024))
            metadata = yaml.safe_load((candidate / 'pack.yaml').read_bytes())
            if (_candidate_hash(candidate) != config['candidate_hash']
                    or metadata['pack']['version'] != config['target_version']):
                raise BindingError('knowledge_candidate_changed')
            candidate_pack_id = metadata['pack']['pack_id']
        intent = {'binding_sha256': self.config_sha256, 'principal': principal,
                  'proposal_id': config['proposal_id'], 'candidate_hash': expected_candidate_hash,
                  'decision': decision, 'reason': reason, 'intent_id': intent_id}
        fingerprint = hashlib.sha256(canonical(intent)).hexdigest()
        directory = Path(config['intents'])
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise BindingError('knowledge_intent_directory_invalid')
        path = directory / (intent_id + '.json')
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            prior = json.loads(protected_bytes(path))
            if prior['fingerprint'] != fingerprint:
                raise BindingError('knowledge_intent_conflict')
            if prior['state'] != 'completed':
                raise BindingError('knowledge_decision_outcome_unknown')
            return prior['result']
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical({'state': 'started', 'fingerprint': fingerprint, 'intent': intent}))
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(directory)
        # After durable intent, errors remain unknown; never auto-repeat SDK writes.
        admin = KnowledgeStore(Path(config['workspace']), self._context())
        try:
            # Original SDK does not let admin read private proposals without a
            # grant either. Grant validates the stored exact proposal/base hash.
            grant = admin.grant_review(config['proposal_id'], expected_candidate_hash, config['reviewer_actor'])
        finally:
            admin.close()
        reviewer = KnowledgeStore(Path(config['workspace']), self._context(reviewer=True))
        try:
            proposal = reviewer.get_proposal(config['proposal_id'])
            if (proposal['status'] != 'proposed' or proposal['visibility'] != 'private'
                    or proposal['channel'] != 'model' or proposal['base_hash'] != expected_candidate_hash
                    or proposal['version'] != config['target_version'] or proposal['pack_id'] != candidate_pack_id):
                raise BindingError('knowledge_proposal_changed')
            result = reviewer.review(config['proposal_id'], decision, reason=reason,
                                     evidence_refs=[{'locator': config['candidate'], 'version': config['target_version'],
                                                     'hash': expected_candidate_hash}])
        finally:
            reviewer.close()
        output = {'decision': result, 'grant': grant, 'principal': principal,
                  'human_identity_claimed': False, 'release_or_pin_performed': False}
        # O_EXCL journal stays started until this complete record is atomically durable.
        temporary = path.with_suffix('.completed')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical({'state': 'completed', 'fingerprint': fingerprint, 'result': output}))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(directory)
        return output

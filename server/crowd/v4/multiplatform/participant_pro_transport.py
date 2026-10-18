"""Local participant RPC transport; auth refresh remains in the original extension.

No browser launch, page creation, credential export or automatic RPC retries.
The purchased Pro installation remains separate from these public adapter files.
"""
import json
from pathlib import Path
import shutil
import subprocess
import uuid


class ParticipantTransportError(ValueError):
    pass


class ParticipantProTransport:
    def __init__(self, profile, subject, installation_id, node=None, generation=None):
        profile = Path(profile)
        if not profile.is_absolute() or profile.is_symlink():
            raise ParticipantTransportError('invalid_participant_scope')
        for value in (subject, installation_id):
            if str(uuid.UUID(value)) != value:
                raise ParticipantTransportError('invalid_participant_scope')
        if generation is not None and (type(generation) is not int or generation < 0):
            raise ParticipantTransportError('invalid_participant_scope')
        self.binding = dict(profile=str(profile), subject=subject, installation_id=installation_id, generation=generation)
        self.node = node or shutil.which('node')
        if not self.node:
            raise ParticipantTransportError('participant_node_runtime_missing')

    def __call__(self, action, params):
        if action not in ('scope', 'verify_platform_principal', 'pro_claim', 'pro_guard', 'pro_submit', 'pro_status', 'pro_finish', 'pro_receipt') or not isinstance(params, dict):
            raise ParticipantTransportError('invalid_participant_action')
        if action != 'scope' and self.binding['generation'] is None:
            self.scope()
        payload = json.dumps({**self.binding, 'action': action, 'params': params}, ensure_ascii=False)
        if len(payload.encode()) > 280000:
            raise ParticipantTransportError('invalid_participant_params')
        try:
            result = subprocess.run([self.node, str(Path(__file__).with_name('participant_pro_rpc.mjs'))],
                                    input=payload, text=True, capture_output=True, timeout=35, check=False)
            value = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise ParticipantTransportError('participant_rpc_outcome_unknown') from None
        if result.returncode or not isinstance(value, dict) or value.get('ok') is not True or 'result' not in value:
            known = {'invalid_participant_transport', 'invalid_participant_scope', 'invalid_participant_action',
                     'invalid_participant_params', 'invalid_platform_principal', 'participant_profile_invalid',
                     'participant_port_invalid', 'participant_listener_invalid', 'participant_profile_changed',
                     'participant_worker_missing', 'participant_worker_invalid', 'participant_scope_changed',
                     'participant_writer_busy'}
            if isinstance(value, dict) and value.get('error') in known:
                raise ParticipantTransportError(value['error'])
            raise ParticipantTransportError('participant_rpc_outcome_unknown')
        return value['result']

    def scope(self):
        value = self('scope', {})
        if (not isinstance(value, dict) or value.get('subject') != self.binding['subject'] or
                value.get('installation_id') != self.binding['installation_id'] or
                type(value.get('generation')) is not int or value['generation'] < 0):
            raise ParticipantTransportError('participant_scope_changed')
        if self.binding['generation'] is not None and value['generation'] != self.binding['generation']:
            raise ParticipantTransportError('participant_scope_changed')
        self.binding['generation'] = value['generation']
        return {key:value[key] for key in ('subject', 'installation_id')}

    def verify_platform_principal(self, uid):
        return self('verify_platform_principal', {'uid': uid})

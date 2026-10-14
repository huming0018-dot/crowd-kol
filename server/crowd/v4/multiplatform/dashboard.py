#!/usr/bin/env python3
"""Local-only task UI for a separately installed MediaCrawler executor."""
import argparse
from copy import deepcopy
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, quote
import uuid
import webbrowser

HERE = Path(__file__).resolve().parent
ACTIONS = {'capabilities', 'start', 'status', 'stop', 'import', 'list'}
DELIVERY_ERRORS = {'invalid_capture_retry', 'capture_not_quarantined', 'owner_authorization_required',
    'worker_revoked', 'principal_denied', 'task_not_found', 'task_paused', 'task_stopped',
    'delivery_state_conflict', 'delivery_not_deferred', 'delivery_recovery_busy', 'controller_busy',
    'cloud_outcome_unknown', 'cloud_read_unavailable', 'cloud_delivery_lease_unavailable',
    'cloud_delivery_lease_denied', 'delivery_binding_mismatch', 'delivery_resume_required',
    'task_scope_denied', 'cloud_upgrade_required', 'delivery_recovery_unavailable', 'delivery_retry_run_mismatch',
    'delivery_retry_denied', 'delivery_resume_denied', 'cloud_controller_busy'}


class Application:
    def __init__(self, root, mc_root=None, collector_roots=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config_path = self.root / 'dashboard-config.json'
        self.runner_root = self.root / 'collector'
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.analysis_jobs = None
        self.owner_tasks = None
        self.results_store = None
        self.media_jobs = None
        self.light_transcripts = None
        self.cloud_worker = None
        self.cloud_client = None
        config = {}
        try:
            config = json.loads(self.config_path.read_text())
            if not isinstance(config, dict):
                raise ValueError('invalid_configuration')
            self.mc_root = config.get('mc_root', '')
        except (OSError, ValueError):
            config = {}
            self.mc_root = ''
        registered = config.get('collector_roots', [])
        preferred = config.get('preferred_session_by_platform', {})
        from account_sessions import PLATFORMS, identifier
        if not isinstance(preferred, dict) or any(platform not in PLATFORMS for platform in preferred):
            raise ValueError('invalid_preferred_sessions')
        self.preferred_session_by_platform = {platform: identifier(session_id)
                                              for platform, session_id in preferred.items()}
        if not isinstance(registered, list) or any(not isinstance(p, str) for p in registered):
            raise ValueError('invalid_collector_roots')
        self.collector_roots = list(dict.fromkeys(Path(p).expanduser().resolve()
                                    for p in registered + list(collector_roots or [])))
        for path in self.collector_roots:
            if not path.is_dir() or not (path / 'runs').is_dir() or not (path / 'sessions').is_dir():
                raise ValueError('collector_root_required')
        if mc_root:
            self.mc_root = str(Path(mc_root).expanduser().resolve())
        if not self.mc_root:
            candidates = [p for p in (Path.home() / 'WorkBuddy').glob('*/MediaCrawler')
                          if (p / 'main.py').is_file() and (p / 'LICENSE').is_file()]
            if len(candidates) == 1:
                self.mc_root = str(candidates[0].resolve())
        if collector_roots:
            self._save_config()
        cloud_config = self.root / 'cloud-config.json'
        if cloud_config.exists() or cloud_config.is_symlink():
            from cloud_sync import CloudClient, CloudOwnerAdapter, CloudWorker
            self.cloud_client = CloudClient(cloud_config, 'owner')
            self.owner_tasks = CloudOwnerAdapter(self.cloud_client, self._validate_cloud_existing)
            worker_client = CloudClient(cloud_config, 'worker')
            self.cloud_worker = CloudWorker(self.root, worker_client, self.task_run,
                                           self._cloud_session, self._cloud_existing,
                                           postprocessing_callback=self._light_postprocessing)
            self.cloud_worker.start_scheduler()
        else:
            from owner_tasks import OwnerTasks
            self.owner_tasks = OwnerTasks(self.root, self.task_run, postprocessing_callback=self._light_postprocessing)
        self.owner_tasks.start_scheduler()
        from watchlists import Watchlists
        self.watchlists = Watchlists(self.root, self.owner_tasks)
        self.watchlists.start_scheduler()
        from health_events import HealthEvents
        self.health_events = HealthEvents(self.root)
        if self.cloud_worker is not None:
            self.health_events.start(self.cloud_worker.status)

    def health(self):
        value = self.health_events.status()
        value.update(ok=True, storage_scope='cloud' if self.cloud_worker else 'local')
        return value

    def _cloud_session(self, lease):
        from account_sessions import AccountSessions
        candidates = []
        for root in self._roots():
            for item in AccountSessions(root).list()['sessions']:
                if item['platform'] == lease['platform'] and item['state'] not in (
                        'account_changed', 'identity_unverified', 'waiting_login', 'checking',
                        'logged_out', 'check_failed'):
                    candidates.append(item)
        ready = [item for item in candidates if item.get('authorized_for_run')]
        preferred = self.preferred_session_by_platform.get(lease['platform'])
        if preferred:
            selected = [item for item in candidates if item['session_id'] == preferred]
            if len(selected) != 1:
                raise ValueError('login_session_required' if not selected else 'collector_session_ambiguous')
            return selected[0]['session_id']
        choices = ready or candidates
        if len(choices) > 1:
            raise ValueError('collector_session_ambiguous')
        if not choices:
            raise ValueError('login_session_required')
        return choices[0]['session_id']

    def _cloud_existing(self, lease):
        if not isinstance(lease.get('record_refs'), list) or len(lease['record_refs']) > 200:
            raise ValueError('existing_saved_selection_unavailable')
        from results_store import ResultsStore
        from mc_runner import PLATFORMS
        from existing_saved import validate_existing_targets
        platform = PLATFORMS[lease['platform']]
        store = ResultsStore(self.root)
        records = []
        for ref in lease.get('record_refs', []):
            if ref.get('version_hash'):
                records.append(store.saved_version(platform, ref['content_id'],
                               ref.get('kind', 'content'), ref['version_hash']))
                continue
            result = store.list_results(
                filters={'platform': platform, 'content_id': ref['content_id'],
                         'kind': ref.get('kind', 'content')}, limit=200)
            chosen = result['items']
            if len(chosen) != 1:
                raise ValueError('existing_saved_selection_unavailable')
            records.extend(chosen)
        if records:
            validate_existing_targets(lease, records, store)
        return records

    def _validate_cloud_existing(self, payload):
        if (payload.get('delivery_basis') != 'existing_saved' or payload.get('mode') != 'detail'
                or not isinstance(payload.get('platforms'), list) or 'bili' not in payload['platforms']):
            return
        mapping = payload.get('record_refs_by_platform') or {}
        targets = payload.get('targets_by_platform') or {}
        if not isinstance(mapping, dict) or not isinstance(targets, dict):
            raise ValueError('existing_saved_target_unverified')
        refs = mapping.get('bili', [])
        if (not isinstance(refs, list) or len(refs) > 200 or any(not isinstance(ref, dict)
                or not isinstance(ref.get('content_id'), str) or not ref['content_id']
                or ref.get('kind', 'content') not in ('content','comment','media','dynamic','author')
                or ref.get('platform', 'bilibili') != 'bilibili' for ref in refs)):
            raise ValueError('existing_saved_target_unverified')
        if refs:
            self._cloud_existing({'platform':'bili', 'record_refs':refs,
                'request':{'mode':'detail', 'targets':targets.get('bili')}})

    def cloud(self, action, payload):
        if not isinstance(payload, dict):
            raise ValueError('invalid_cloud_request')
        if action in ('delivery_status', 'retry_delivery'):
            if action == 'delivery_status' and payload or action == 'retry_delivery' and set(payload) != {'capture_ids'}:
                raise ValueError('invalid_delivery_request')
            if self.cloud_client is None or self.cloud_worker is None:
                if action == 'delivery_status':
                    return {'ok': True, 'storage_scope': 'local', 'available': False, 'reason': 'not_connected'}
                raise ValueError('cloud_configuration_required')
            if getattr(self.cloud_client, 'role', None) != 'owner':
                raise ValueError('owner_authorization_required')
            if action == 'retry_delivery':
                ids = payload['capture_ids']
                if not isinstance(ids, list) or not 1 <= len(ids) <= 2000:
                    raise ValueError('invalid_delivery_request')
                try:
                    valid = all(isinstance(value, str) and str(uuid.UUID(value)) == value for value in ids)
                except ValueError:
                    valid = False
                if not valid or len(set(ids)) != len(ids):
                    raise ValueError('invalid_delivery_request')
            method = getattr(self.cloud_worker, action, None)
            if not callable(method):
                if action == 'delivery_status':
                    return {'ok': True, 'storage_scope': 'cloud', 'available': False, 'reason': 'upgrade_required'}
                raise ValueError('cloud_upgrade_required')
            try:
                value = method() if action == 'delivery_status' else method(ids, self.cloud_client)
            except (ValueError, TypeError, OSError) as error:
                raise ValueError(str(error) if str(error) in DELIVERY_ERRORS else 'delivery_recovery_unavailable') from None
            schema = 'crowd-delivery-status-v1' if action == 'delivery_status' else 'crowd-delivery-retry-v1'
            if (not isinstance(value, dict) or value.get('schema') != schema or
                    action == 'delivery_status' and not isinstance(value.get('groups'), list) or
                    action == 'retry_delivery' and (value.get('accepted') is not True or value.get('state') != 'queued')):
                raise ValueError('cloud_read_unavailable' if action == 'delivery_status' else 'cloud_outcome_unknown')
            if action == 'retry_delivery':
                requeued = value.get('requeued_capture_ids')
                if (not isinstance(requeued, list) or not all(isinstance(item, str) and item in ids for item in requeued)
                        or len(set(requeued)) != len(requeued)):
                    raise ValueError('cloud_outcome_unknown')
            return {**value, 'ok': True, 'storage_scope': 'cloud', 'available': True}
        if action == 'status' and not payload:
            if self.cloud_worker is None:
                return {'ok': True, 'storage_scope': 'local', 'worker_state': 'not_connected'}
            return {'ok': True, 'storage_scope': 'cloud', **self.cloud_worker.status()}
        if action == 'results' and set(payload) == {'task_id'} and self.cloud_client:
            return {'ok': True, **self.cloud_client.call('results', payload)}
        if action == 'participant_health' and not payload:
            if self.cloud_client is None:
                return {'ok': True, 'storage_scope': 'local', 'participants': [], 'events': []}
            return {'ok': True, 'storage_scope': 'cloud', **self.cloud_client.call('participant_health', {})}
        if action == 'workflow_events' and not payload:
            if self.cloud_worker is None:
                return {'ok': True, 'storage_scope': 'local', 'events': [], 'coverage': 'not_connected'}
            return {'ok': True, 'storage_scope': 'local', 'coverage': 'machine_lifecycle_phases',
                    **self.cloud_worker.workflow_events.status()}
        if action in ('unified_preview', 'unified_create', 'unified_dispatches'):
            from owner_tasks import FIELDS
            from cloud_sync import CloudError
            fields = FIELDS | {'delivery_basis', 'record_refs_by_platform', 'start_page', 'interval_seconds', 'wordcloud'}
            if (action == 'unified_dispatches' and set(payload) - {'idempotency_key'} or
                    action != 'unified_dispatches' and set(payload) - fields or
                    (action != 'unified_dispatches' or 'idempotency_key' in payload) and
                    (not isinstance(payload.get('idempotency_key'), str) or not 1 <= len(payload['idempotency_key']) <= 160 or
                     any(ord(c) < 32 or ord(c) == 127 for c in payload['idempotency_key']))):
                raise ValueError('invalid_cloud_request')
            if self.cloud_client is None:
                return {'ok': True, 'storage_scope': 'local', 'available': False, 'reason': 'not_connected'}
            if action in ('unified_preview', 'unified_create'):
                self._validate_cloud_existing(payload)
            try:
                value = self.cloud_client.call(action, payload)
            except CloudError as error:
                if str(error) in ('invalid_action', 'unknown_action', 'unsupported_action', 'invalid_cloud_action', 'principal_denied'):
                    return {'ok': True, 'storage_scope': 'cloud', 'available': False, 'reason': 'upgrade_or_access_required'}
                raise
            schema = 'crowd-unified-dispatch-list-v1' if action == 'unified_dispatches' else 'crowd-unified-dispatch-v1'
            if value.get('schema') != schema:
                raise CloudError('cloud_read_unavailable' if action != 'unified_create' else 'cloud_outcome_unknown')
            return {**value, 'ok': True, 'storage_scope': 'cloud', 'available': True}
        if action in ('unified_status', 'node_events'):
            allowed = {'limit'} if action == 'unified_status' else {'limit', 'after_id', 'installation_id'}
            if set(payload) - allowed:
                raise ValueError('invalid_cloud_request')
            if 'limit' in payload and (type(payload['limit']) is not int or
                    not 1 <= payload['limit'] <= (100 if action == 'unified_status' else 200)):
                raise ValueError('invalid_cloud_request')
            if 'after_id' in payload and (type(payload['after_id']) is not int or not 0 <= payload['after_id'] <= 2**53-1):
                raise ValueError('invalid_cloud_request')
            if 'installation_id' in payload:
                candidate = payload['installation_id']
                if not isinstance(candidate, str) or str(uuid.UUID(candidate)) != candidate:
                    raise ValueError('invalid_cloud_request')
            if self.cloud_client is None:
                return {'ok': True, 'storage_scope': 'local', 'available': False, 'reason': 'not_connected'}
            from cloud_sync import CloudError
            try:
                value = self.cloud_client.call(action, payload)
            except CloudError as error:
                if str(error) == 'principal_denied':
                    return {'ok': True, 'storage_scope': 'cloud', 'available': False, 'reason': 'upgrade_or_access_required'}
                if str(error) not in ('invalid_action', 'unknown_action', 'unsupported_action', 'invalid_cloud_action'):
                    raise
                return {'ok': True, 'storage_scope': 'cloud', 'available': False, 'reason': 'upgrade_required'}
            schema = 'crowd-unified-status-v1' if action == 'unified_status' else 'crowd-node-events-v1'
            if value.get('schema') != schema:
                return {'ok': True, 'storage_scope': 'cloud', 'available': False, 'reason': 'upgrade_required'}
            return {**value, 'ok': True, 'storage_scope': 'cloud', 'available': True}
        raise ValueError('invalid_cloud_action')

    def configure(self, body):
        if set(body) != {'mc_root'} or not isinstance(body['mc_root'], str):
            raise ValueError('invalid_configuration')
        path = Path(body['mc_root']).expanduser().resolve()
        if not all((path / name).is_file() for name in ['main.py', 'LICENSE']):
            raise ValueError('mediacrawler_directory_required')
        with self.lock:
            self.mc_root = str(path)
            self._save_config()
        return {'ok': True, 'mc_root': self.mc_root}

    def _save_config(self):
        data = json.dumps({'mc_root': self.mc_root,
                           'preferred_session_by_platform': self.preferred_session_by_platform,
                           'collector_roots': [str(p) for p in self.collector_roots]}).encode()
        temporary = self.root / ('config-' + secrets.token_hex(8))
        with os.fdopen(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(self.config_path)

    def _prefer_session(self, value):
        # CloudWorker invokes the selector only before dispatch without a bound session.
        with self.lock:
            self.preferred_session_by_platform[value['platform']] = value['session_id']
            self._save_config()
        return value

    def _roots(self):
        return list(dict.fromkeys([self.runner_root, *self.collector_roots]))

    def _registered_run_root(self, run_id):
        try:
            if not isinstance(run_id, str) or str(uuid.UUID(run_id)) != run_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('invalid_run_id') from None
        matches = [p for p in self._roots() if (p / 'runs' / run_id).is_dir()
                   and not (p / 'runs' / run_id).is_symlink()]
        if len(matches) != 1:
            raise ValueError('collector_run_ambiguous' if matches else 'run_not_found')
        return matches[0]

    def _start_root(self, payload):
        session_id = payload.get('session_id')
        if not session_id:
            return self.runner_root
        try:
            if not isinstance(session_id, str) or str(uuid.UUID(session_id)) != session_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('invalid_session_id') from None
        matches = [p for p in self._roots() if (p / 'sessions' / session_id).is_dir()
                   and not (p / 'sessions' / session_id).is_symlink()]
        if len(matches) > 1:
            raise ValueError('collector_session_ambiguous')
        if not matches:
            raise ValueError('session_not_found')
        # identity.json is platform metadata; browser_data and credentials stay untouched.
        try:
            identity = json.loads((matches[0] / 'sessions' / session_id / 'identity.json').read_text())
            if identity.get('platform') != payload.get('platform'):
                raise ValueError('session_platform_mismatch')
        except (OSError, TypeError, AttributeError, json.JSONDecodeError):
            raise ValueError('session_identity_unavailable') from None
        return matches[0]

    def _call_runner(self, root, action, payload):
        command = [sys.executable, str(HERE / 'mc_runner.py'), '--root', str(root),
                   '--mc-root', self.mc_root, action]
        # The runner consumes JSON, never a shell command or browser credentials.
        try:
            result = subprocess.run(command, input=json.dumps(payload), text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=15, check=False)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': 'runner_response_timeout_check_runs_before_retry'}
        if len(result.stdout.encode()) > 10 * 1024 * 1024:
            return {'ok': False, 'error': 'runner_result_too_large'}
        try:
            value = json.loads(result.stdout)
        except ValueError:
            return {'ok': False, 'error': 'runner_unavailable'}
        if not isinstance(value, dict):
            return {'ok': False, 'error': 'invalid_runner_result'}
        return value

    def run(self, action, payload):
        if action not in ACTIONS or not isinstance(payload, dict):
            raise ValueError('invalid_action')
        if not self.mc_root:
            raise ValueError('configure_executor_first')
        if action == 'list':
            if payload:
                raise ValueError('invalid_list_request')
            runs = []
            for root in self._roots():
                response = self._call_runner(root, action, payload)
                if response.get('ok') is False:
                    return response
                items = response.get('result', response).get('runs', [])
                if not isinstance(items, list):
                    raise ValueError('invalid_runner_result')
                runs.extend(items)
            seen = set()
            for item in runs:
                run_id = item.get('run_id')
                if run_id in seen:
                    raise ValueError('collector_run_ambiguous')
                seen.add(run_id)
            return {'ok': True, 'result': {'runs': runs}}
        root = (self._registered_run_root(payload.get('run_id')) if action in ('status', 'stop', 'import')
                else self._start_root(payload) if action == 'start' else self.runner_root)
        value = self._call_runner(root, action, payload)
        if action == 'import' and value.get('ok') is not False:
            imported = value.get('result', value)
            if isinstance(imported, dict) and 'records' in imported:
                try:
                    from results_store import ResultsStore
                    with self.lock:
                        if self.results_store is None:
                            self.results_store = ResultsStore(self.root)
                    persisted = self.results_store.ingest(imported)
                    imported['local_results_revision'] = persisted['results_revision']
                except (ValueError, TypeError, OSError, sqlite3.Error):
                    imported['local_results_error'] = 'results_store_write_failed'
        return value

    def task_run(self, action, payload):
        """A parent cannot report success before its library write succeeds."""
        if action == 'account_status':
            return self.accounts('status', payload)
        response = self.run(action, payload)
        imported = response.get('result', response)
        if action == 'import' and imported.get('local_results_error'):
            # Original files and the run stay intact. OwnerTasks retains active_run_id
            # and retries this read/import, without starting another source action.
            return {'ok': False, 'error': 'local_results_persistence_failed'}
        if action == 'import' and self.cloud_worker is None and response.get('ok') is not False:
            try:self._light_postprocessing('enqueue', payload)
            except (ValueError, OSError):pass
        return response

    def _light_postprocessing(self, action, payload):
        if action == 'tick' and self.light_transcripts is None and not (self.root / 'light-transcripts').exists():return
        if action == 'enqueue':
            from analysis_artifact import _read
            folder = self._registered_run_root(payload['run_id']) / 'runs' / payload['run_id']
            manifest = _read(folder / 'manifest.json', 200000)[0]
            if manifest.get('request', {}).get('platform_options', {}).get('transcript_only') is not True:return
        if self.light_transcripts is None:
            from light_transcripts import LightTranscripts
            self.process_media('capabilities', {})
            with self.lock:
                if self.light_transcripts is None:
                    self.light_transcripts = LightTranscripts(self.root, self.media_jobs,
                        lambda run_id: self._registered_run_root(run_id) / 'runs' / run_id)
        if action == 'enqueue':return self.light_transcripts.enqueue(payload['run_id'])
        if action == 'tick':return self.light_transcripts.tick()
        raise ValueError('invalid_light_transcript_action')

    def accounts(self, action, payload):
        from account_sessions import AccountSessions, identifier
        if not isinstance(payload, dict):
            raise ValueError('invalid_account_request')
        if action == 'list' and not payload:
            sessions = []
            for root in self._roots():
                sessions.extend(AccountSessions(root).list()['sessions'])
            ids = [s['session_id'] for s in sessions]
            if len(ids) != len(set(ids)):
                raise ValueError('collector_session_ambiguous')
            return {'ok': True, 'sessions': sessions}
        if action=='create_browser_session' and set(payload)=={'platform','port','target_id','browser_fingerprint'}:
            return self._prefer_session(AccountSessions(self._roots()[0]).create_browser_session(**payload))
        session_id = identifier(payload.get('session_id'))
        matches = [root for root in self._roots() if (root/'sessions'/session_id).is_dir()
                   and not (root/'sessions'/session_id).is_symlink()]
        if len(matches) != 1:
            raise ValueError('collector_session_ambiguous' if matches else 'session_not_found')
        store = AccountSessions(matches[0])
        if action == 'status' and set(payload) in ({'session_id'}, {'session_id', 'platform'}):
            return store.status(session_id, payload.get('platform'))
        if action == 'open_login' and set(payload) == {'session_id', 'platform'}:
            return store.open_login(session_id, payload['platform'], self.mc_root)
        if action == 'browser_candidates' and {'session_id'} <= set(payload) <= {'session_id','port','restart_connection','refresh_targets'}:
            if 'restart_connection' in payload and type(payload['restart_connection']) is not bool:
                raise ValueError('invalid_browser_connection_restart')
            if 'refresh_targets' in payload and type(payload['refresh_targets']) is not bool:
                raise ValueError('invalid_browser_target_refresh')
            return store.browser_candidates(session_id,payload.get('port',9222),restart_connection=payload.get('restart_connection',False),refresh_targets=payload.get('refresh_targets',False))
        if action == 'bind_browser' and set(payload)=={'session_id','port','target_id','browser_fingerprint','expected_generation'}:
            return self._prefer_session(store.bind_browser(**payload))
        if action=='use_persistent_browser' and set(payload)=={'session_id','expected_generation'}:
            return self._prefer_session(store.use_persistent_browser(**payload))
        if action == 'cancel_login' and set(payload) == {'session_id'}:
            return store.cancel_login(session_id)
        if action == 'resume_verification' and set(payload) == {'session_id'}:
            return store.resume_verification(session_id)
        if action == 'confirm_same_account' and set(payload) == {'session_id', 'expected_generation', 'confirm_same_account'}:
            return store.confirm_same_account(**payload)
        if action == 'accept_account_switch' and set(payload) == {'session_id', 'expected_generation', 'acknowledge_new_scope'}:
            return store.accept_account_switch(**payload)
        raise ValueError('invalid_account_action')

    def analysis(self, action, payload):
        from analysis_contract import build_snapshot
        from full_analysis import build_analysis_snapshot
        from analysis_jobs import AnalysisJobs
        if not isinstance(payload, dict) or action not in ('start', 'status', 'cancel', 'lookup', 'publish', 'reassemble'):
            raise ValueError('invalid_analysis_action')
        with self.lock:
            if self.analysis_jobs is None:
                self.analysis_jobs = AnalysisJobs(self.root)
        if action == 'publish':
            if set(payload) != {'job_id'}:
                raise ValueError('invalid_analysis_request')
            from analysis_artifact import publish_analysis_artifact
            return publish_analysis_artifact(self.analysis_jobs, self.cloud_client, payload['job_id'])
        if action in ('status', 'cancel', 'reassemble'):
            if set(payload) != {'job_id'}:
                raise ValueError('invalid_analysis_request')
            return getattr(self.analysis_jobs, action)(payload['job_id'])
        fields = {'run_id', 'platform', 'content_id'}
        if action == 'start':
            fields |= {'snapshot_hash', 'allow_model_transfer'}
        if set(payload) - {'entity_ref','derived_refs'} != fields:
            raise ValueError('invalid_analysis_request')
        response = self.run('import', {'run_id': payload['run_id']})
        if response.get('ok') is False:
            raise ValueError('results_not_ready')
        imported = response.get('result', response)
        snapshot = build_snapshot(imported, payload['platform'], payload['content_id'], entity_ref=payload.get('entity_ref'))
        media=self.analysis_jobs.media_inputs(imported,snapshot,payload['run_id'],payload.get('derived_refs'))
        if media['selected']:
            snapshot=build_analysis_snapshot(imported,payload['platform'],payload['content_id'],entity_ref=payload.get('entity_ref'),derived_inputs=media['selected'])
        input_summary = {'scope': snapshot['content']['scope'],
                         'comments': len(snapshot['comments']), 'coverage': snapshot['coverage']}
        if 'entity_ref' in snapshot['content']:
            input_summary.update(entity_ref=snapshot['content']['entity_ref'], kind=snapshot['content']['kind'])
        if media['selected']:input_summary['derived_inputs']=media['selected']
        if 'analysis_batches' in snapshot:
            input_summary['analysis_batches']=len(snapshot['analysis_batches'])
        preview={'derived_options':media['options'],'derived_excluded':media['excluded']}
        if action == 'start':
            if payload['allow_model_transfer'] is not True:
                raise ValueError('analysis_transfer_authorization_required')
            if payload['snapshot_hash'] != snapshot['snapshot_hash']:
                raise ValueError('analysis_snapshot_changed')
            return self.analysis_jobs.start(imported, payload['platform'], payload['content_id'], entity_ref=payload.get('entity_ref'),derived_inputs=media['selected'])
        matching = []
        for folder in self.analysis_jobs.root.iterdir():
            if folder.is_dir() and not folder.is_symlink() and (folder / 'state.json').is_file():
                state = json.loads((folder / 'state.json').read_text())
                if state.get('snapshot_hash') == snapshot['snapshot_hash']:
                    matching.append(state)
        if not matching:
            return {'ok': True, 'state': 'not_started', 'snapshot_hash': snapshot['snapshot_hash'],
                    'input_summary': input_summary,**preview}
        completed = [s for s in matching if s['state'] == 'completed']
        latest = max(completed or matching, key=lambda s: s['created_at'])
        return {**self.analysis_jobs.status(latest['job_id']), 'input_summary': input_summary,**preview}

    def tasks(self, action, payload):
        from owner_tasks import OwnerTasks, parse_batch
        if not isinstance(payload, dict):
            raise ValueError('invalid_task_request')
        if action == 'parse_batch':
            if set(payload) != {'text', 'mode'}:
                raise ValueError('invalid_batch_request')
            parsed = parse_batch(payload['text'], payload['mode'])
            return {**parsed, 'valid': parsed['ok'], 'ok': True}
        with self.lock:
            if self.owner_tasks is None:
                self.owner_tasks = OwnerTasks(self.root, self.task_run)
                self.owner_tasks.start_scheduler()
        if action in ('preview', 'create'):
            options = payload.get('platform_options_by_platform', {})
            light_requested = isinstance(options, dict) and any(isinstance(value, dict) and value.get('transcript_only') is True for value in options.values())
            if light_requested:
                from mc_runner import PLATFORMS
                if not payload.get('platforms') or any(p not in PLATFORMS for p in payload['platforms']):raise ValueError('transcript_only_platform_unsupported')
                capabilities = self.process_media('capabilities', {})
                if not capabilities['asr'] or not capabilities['ffmpeg']:raise ValueError('light_transcript_local_processor_required')
            return getattr(self.owner_tasks, action)(payload)
        if action in ('retry_supplemental', 'reconcile'):
            method = getattr(self.owner_tasks, action, None)
            if method is None:
                raise ValueError('supplemental_requires_cloud_task' if action == 'retry_supplemental' else 'reconciliation_requires_cloud_task')
            return method(payload)
        if action == 'list' and not payload:
            return self._task_stop_projection(self.owner_tasks.list())
        if action in ('status', 'stop', 'resume') and set(payload) == {'task_id'}:
            return self._task_stop_projection(getattr(self.owner_tasks, action)(payload['task_id']))
        raise ValueError('invalid_task_action')

    def _task_stop_projection(self, value):
        # Local diagnostics supplement only the matching cloud child; cloud history stays authoritative.
        from mc_runner import status, BridgeError
        from discovery import unavailable_failure
        value=deepcopy(value)
        for task in ([value['task']] if isinstance(value.get('task'),dict) else value.get('tasks',[])):
            for child in task.get('children',[]):
                run_id = child.get('local_run_id') or next(iter(reversed(child.get('runs', []))), None)
                if run_id and self.media_jobs is not None:
                    try:child['video_text_jobs'] = self.media_jobs.list_metadata(run_id)['jobs']
                    except (ValueError,OSError,BridgeError):child['video_text_error']='saved_media_metadata_unavailable'
                if run_id and self.light_transcripts is not None:
                    try:
                        summary = self.light_transcripts.status(run_id)
                        if summary:
                            child['light_transcript'] = summary
                            if self.media_jobs is not None:
                                summary['visual_jobs'] = child.get('video_text_jobs', [])
                    except (ValueError, OSError):pass
                if child.get('state') not in ('stopped','failed') or not child.get('local_run_id'):continue
                try:
                    root=self._registered_run_root(child['local_run_id'])
                    current=status(root,{'run_id':child['local_run_id']})
                    if child.get('state')=='stopped' and current.get('state')=='stopped' and current.get('stop_context'):
                        child['local_stop_context']=current['stop_context']
                        child['local_stop_reason']=current['stop_context']['reason']
                    elif child.get('state')=='failed' and unavailable_failure(current):
                        child['local_failure_reason']='discovery_empty_or_unavailable'
                except (BridgeError,ValueError,OSError):pass
        return value

    def results(self, action, payload):
        from results_store import ResultsStore
        if not isinstance(payload, dict):
            raise ValueError('invalid_results_request')
        with self.lock:
            if self.results_store is None:
                self.results_store = ResultsStore(self.root)
        if action == 'ingest' and set(payload) == {'run_id'}:
            response = self.run('import', payload)
            if response.get('ok') is False:
                raise ValueError(response.get('error', 'results_not_ready'))
            return self.results_store.ingest(response.get('result', response))
        fields = {
            'list': {'filters', 'revision', 'limit', 'offset', 'cursor'},
            'detail': {'platform', 'content_id', 'revision', 'entity_ref'},
            'evaluate': {'platform', 'content_id', 'value', 'tags', 'evaluator_ref', 'revision', 'entity_ref'},
            'export': {'format', 'filters', 'revision'},
        }
        if action not in fields or set(payload) - fields[action]:
            raise ValueError('invalid_results_action')
        method = 'list_results' if action == 'list' else action
        return getattr(self.results_store, method)(**payload)

    def watches(self, action, payload):
        if not isinstance(payload, dict):
            raise ValueError('invalid_watchlist_request')
        if action in ('create', 'preview'):
            return getattr(self.watchlists, action)(payload)
        if action == 'list' and not payload:
            return self.watchlists.list()
        if action in ('status', 'stop', 'resume') and set(payload) == {'watch_id'}:
            return getattr(self.watchlists, action)(payload['watch_id'])
        raise ValueError('invalid_watchlist_action')

    def media_file(self, body, artifact=False):
        if set(body) != {'run_id', 'path'} or not isinstance(body['path'], str):
            raise ValueError('invalid_media_request')
        run_id = str(uuid.UUID(body['run_id']))
        if run_id != body['run_id']:
            raise ValueError('invalid_run_id')
        response = self.run('import', {'run_id': run_id})
        if response.get('ok') is False:
            raise ValueError('results_not_ready')
        media = response.get('result', response).get('artifacts' if artifact else 'media', [])
        if body['path'] not in {item['path'] for item in media}:
            raise ValueError('media_not_in_task')
        run = self._registered_run_root(run_id) / 'runs' / run_id
        path = run / body['path']
        if path.is_symlink() or not path.resolve().is_relative_to((run / 'output').resolve()) or not path.is_file():
            raise ValueError('unsafe_media_path')
        if path.stat().st_size > 500 * 1024 * 1024:
            raise ValueError('media_over_download_limit')
        return path

    def process_media(self, action, payload):
        from media_jobs import MediaJobs
        from mc_runner import PLATFORMS
        if not isinstance(payload, dict):
            raise ValueError('invalid_media_processing_request')
        with self.lock:
            if self.media_jobs is None:
                self.media_jobs = MediaJobs(self.root, os.environ.get('CROWD_LOCAL_ASR_MODEL'), os.environ.get('CROWD_LOCAL_ASR_PYTHON'))
        self.media_jobs.subtitle_run_folder = lambda run_id: self._registered_run_root(run_id) / 'runs' / run_id
        if action=='speech_check_bypass' and set(payload)=={'job_id'}:
            saved=self.media_jobs.status(payload['job_id'])
            if (saved.get('kind')!='asr' or saved.get('speech_check') is not True or saved.get('state')!='failed'
                    or saved.get('reason')!='vad_no_speech_detected' or saved.get('speech_precheck',{}).get('has_speech') is not False):
                raise ValueError('speech_check_bypass_not_available')
            imported=self.run('import',{'run_id':saved['run_id']});data=imported.get('result',imported)
            files=[row for row in data.get('media',[]) if row.get('sha256')==saved['asset_sha256'] and row.get('content_id')==saved['content_id']]
            if len(files)!=1:raise ValueError('speech_check_original_media_unavailable')
            return self.process_media('start',{'run_id':saved['run_id'],'path':files[0]['path'],'content_id':saved['content_id'],
                'kind':'asr','asr_engine':saved.get('asr_engine','cpu'),'speech_check':False})
        if action == 'video_ocr_start':
            if not {'run_id','source_job_id'}<=set(payload) or set(payload)-{'run_id','source_job_id','retry','text_region'} or 'retry' in payload and type(payload['retry']) is not bool:raise ValueError('invalid_video_ocr_request')
            region=payload.get('text_region','bottom')
            regions={'bottom':(.67,.82),'top':(.12,.32),'full':(0.,1.)}
            if not isinstance(region,str) or region not in regions:raise ValueError('invalid_video_ocr_region')
            folder = self._registered_run_root(payload['run_id']) / 'runs' / payload['run_id']
            options=({'retry':payload['retry']} if 'retry' in payload else {})
            if 'text_region' in payload:options.update(crop_top=regions[region][0],crop_bottom=regions[region][1])
            return self.media_jobs.start_video_ocr(payload['source_job_id'], folder, **options)
        if action == 'capabilities' and not payload:
            return self.media_jobs.capabilities()
        if action == 'list' and set(payload) == {'run_id'}:
            value = self.media_jobs.list(payload['run_id'])
            from bili_subtitles import load_job
            from analysis_artifact import _read
            folder=self._registered_run_root(payload['run_id'])/'runs'/payload['run_id']
            value['subtitle_observations']=[]
            if (folder/'normalized.json').is_file():
                normalized,_=_read(folder/'normalized.json',32*1024*1024)
                for row in normalized.get('records',[]):
                    if row.get('kind')!='content' or row.get('platform') not in ('weibo','kuaishou','xiaohongshu','zhihu','tieba'):continue
                    from declared_subtitles import CID,register
                    cid=row.get('content_id');ctype=row.get('content_type') if row['platform']=='zhihu' else None
                    if not isinstance(cid,str) or not CID.fullmatch(cid) or ctype not in (None,'answer','article','zvideo'):continue
                    stem=cid+('.'+ctype if ctype else '')
                    discovery=folder/'output'/row['platform']/'subtitle-discovery'/(stem+'.json')
                    if discovery.is_file():
                        observation,_=_read(discovery,200000)
                        if (observation.get('schema')!='crowd-native-subtitle-discovery-v1' or observation.get('provider')!=row['platform'] or observation.get('content_id')!=cid or observation.get('local_run_id')!=payload['run_id']):raise ValueError('subtitle_observation_changed')
                        value['subtitle_observations'].append({k:observation.get(k) for k in ('provider','content_id','status','reason')})
                    caption=folder/'output'/row['platform']/'declared-subtitles'/(stem+'.json')
                    if caption.is_file():
                        saved,_=_read(caption,200000)
                        if saved.get('status')=='available':register(self.media_jobs,folder,cid,ctype)
            for path in sorted((self.root/'subtitle-jobs').glob('*.json')):
                item,_=_read(path,200000)
                if item.get('run_id')==payload['run_id']:value['jobs'].append(load_job(self.media_jobs,path.stem))
            if self.light_transcripts is not None:
                queued = self.light_transcripts.status(payload['run_id'])
                for asset in (queued or {}).get('assets', []):
                    if asset.get('job_id') and asset['job_id'] not in {job['job_id'] for job in value['jobs']}:
                        value['jobs'].append(self.media_jobs.status(asset['job_id']))
            return value
        if action == 'status' and set(payload)=={'job_id'}:
            from bili_subtitles import load_job
            from transcript_artifact import uid
            if (self.root/'subtitle-jobs'/(uid(payload['job_id'])+'.json')).exists():return load_job(self.media_jobs,payload['job_id'])
        if action in ('status', 'cancel', 'resume') and set(payload) == {'job_id'}:
            return getattr(self.media_jobs, action)(payload['job_id'])
        if action in ('transcript_cloud_status', 'transcript_cloud_save', 'transcript_cloud_get'):
            if set(payload) != {'job_id'}:
                raise ValueError('invalid_transcript_cloud_request')
            from transcript_artifact import transcript_cloud
            return transcript_cloud(self.media_jobs, self.cloud_client, payload['job_id'], action.rsplit('_', 1)[1])
        if action in ('quality_lookup', 'transcript_revision', 'optimization_preview', 'optimization_apply') or action == 'playback':
            spec = importlib.util.spec_from_file_location('crowd_transcript_quality', HERE.parent / 'postprocess' / 'transcript_quality.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            quality = module.TranscriptQuality(self.root)
        if action in ('optimization_preview', 'optimization_apply'):
            expected={'job_id'} if action=='optimization_preview' else {'job_id','expected_result_sha256','expected_plan_sha256'}
            if set(payload)!=expected:raise ValueError('invalid_transcript_optimization_request')
            from transcript_context import context
            saved=quality.validate(payload['job_id']);source_context,references=context(self,saved)
            if action=='optimization_preview':return quality.optimization_preview(payload['job_id'],source_context,references)
            value=quality.create_optimized_revision(payload['job_id'],payload['expected_result_sha256'],payload['expected_plan_sha256'],source_context,references)
            return {**self.media_jobs.status(value['job_id']),'source_requests':0,'model_calls':0}
        if action == 'quality_lookup' and set(payload) == {'job_id'}:
            return quality.lookup(payload['job_id'])
        if action == 'transcript_revision' and set(payload) == {'job_id', 'expected_result_sha256', 'edits', 'reviewer_kind', 'acknowledge_new_version'}:
            value = quality.create_revision(payload['job_id'], payload['expected_result_sha256'], payload['edits'], payload['reviewer_kind'], payload['acknowledge_new_version'])
            return {**self.media_jobs.status(value['job_id']), 'source_requests': 0, 'model_calls': 0}
        if action == 'playback' and set(payload) == {'job_id', 'asset_sha256'}:
            state = self.media_jobs.status(payload['job_id'])
            source = quality.lookup(payload['job_id'])['source_job_id'] if state.get('text_revision') else payload['job_id']
            return self.media_jobs.playback(source, payload['asset_sha256'])
        if action == 'video_file' and set(payload) == {'job_id','asset_sha256'}:
            return self.media_jobs.video_file(payload['job_id'],payload['asset_sha256'])
        if action in ('native_video_cloud_status', 'native_video_cloud_save', 'native_video_cloud_file'):
            if set(payload) not in ({'run_id', 'content_id', 'asset_sha256'}, {'run_id', 'content_id', 'asset_sha256', 'entity_ref'}):
                raise ValueError('invalid_native_video_cloud_request')
            from media_native import prepare_native_video, publish_native_video, native_video_cloud_status, download_native_video
            folder = self._registered_run_root(payload['run_id']) / 'runs' / payload['run_id']
            args = (self.media_jobs, self.cloud_client, folder, payload['content_id'], payload['asset_sha256'], payload.get('entity_ref'))
            if action == 'native_video_cloud_status':
                return native_video_cloud_status(*args)
            if self.cloud_client is None:
                raise ValueError('cloud_configuration_required')
            if action == 'native_video_cloud_save':
                # Validate local identity and the video track before any storage initialization.
                prepare_native_video(*args)
                self.cloud_client.call('media_storage_init', {})
                return publish_native_video(*args)
            return download_native_video(*args)
        if action in ('video_cloud_status','video_cloud_save','video_cloud_file'):
            fields={'job_id'}|({'asset_sha256'} if action=='video_cloud_file' else set())
            if set(payload)!=fields:raise ValueError('invalid_media_cloud_request')
            from media_cloud import media_video_cloud_status,publish_media_video,download_media_video,_job_id
            job_id=_job_id(payload['job_id'])
            if action=='video_cloud_status':return media_video_cloud_status(self.media_jobs,self.cloud_client,job_id)
            if self.cloud_client is None:raise ValueError('cloud_configuration_required')
            if action=='video_cloud_save':
                state=self.media_jobs.status(job_id)
                if state.get('state')!='completed' or state.get('kind')!='complete_video':raise ValueError('media_cloud_not_completed')
                self.cloud_client.call('media_storage_init',{})
                return publish_media_video(self.media_jobs,self.cloud_client,job_id)
            value=download_media_video(self.media_jobs,self.cloud_client,job_id)
            if value['sha256']!=payload['asset_sha256']:raise ValueError('media_cloud_download_mismatch')
            return value
        if action in ('video_preview','video_start'):
            from complete_video import source_reference,public_reference
            fields={'run_id','content_id'}|({'reference_sha256','allow_download'} if action=='video_start' else set())
            if set(payload)!=fields:raise ValueError('invalid_complete_video_request')
            root=self._registered_run_root(payload['run_id'])
            imported=self.run('import',{'run_id':payload['run_id']})
            records=imported.get('result',imported).get('records',[])
            candidates=[r for r in records if r.get('kind')=='content' and r.get('platform')=='douyin' and r.get('content_id')==payload['content_id']]
            if len(candidates)!=1:raise ValueError('video_content_identity_ambiguous')
            reference=source_reference(root/'runs'/payload['run_id'],payload['run_id'],payload['content_id'])
            if action=='video_preview':return public_reference(reference)
            if payload['allow_download'] is not True:raise ValueError('video_download_authorization_required')
            if payload['reference_sha256']!=reference['reference_sha256']:raise ValueError('video_reference_changed')
            return self.media_jobs.start_video(reference)
        if action in ('start','preview') and {'run_id','path','content_id','kind'}<=set(payload)<={'run_id','path','content_id','kind','asr_engine','text_region','speech_check'}:
            if 'speech_check' in payload and (action!='start' or payload['kind']!='asr' or type(payload['speech_check']) is not bool):raise ValueError('invalid_speech_check')
            if 'asr_engine' in payload and (payload['kind'] != 'asr' or payload['asr_engine'] not in ('cpu', 'mlx')):
                raise ValueError('invalid_asr_engine')
            if payload.get('asr_engine') == 'mlx' and payload['asr_engine'] not in self.media_jobs.capabilities().get('asr_engines', []):
                raise ValueError('mac_asr_engine_not_configured')
            if 'text_region' in payload and (payload['kind']!='video_ocr' or action!='start'):raise ValueError('invalid_video_ocr_request')
            source = self.media_file({key: payload[key] for key in ('run_id', 'path')})
            imported = self.run('import', {'run_id': payload['run_id']})
            result = imported.get('result', imported)
            records = result.get('records', [])
            candidates = [r for r in records if r.get('kind') in ('content', 'dynamic') and r.get('content_id') == payload['content_id']]
            files = [item for item in result.get('media', []) if item.get('path') == payload['path']]
            if payload['path'].startswith('output/zhihu/') or any(item.get('platform') == 'zhihu' for item in files):
                if len(files) != 1 or files[0].get('content_id') != payload['content_id']:
                    raise ValueError('media_content_not_in_task')
                source_type = files[0].get('source_content_type')
                candidates = [row for row in candidates if row.get('platform') == 'zhihu']
                if source_type not in ('answer', 'article', 'zvideo') or len(candidates) != 1 or candidates[0].get('content_type') != source_type:
                    raise ValueError('media_content_identity_ambiguous')
            if not candidates:
                raise ValueError('media_content_not_in_task')
            platform = candidates[0]['platform']
            if platform in PLATFORMS:
                platform = PLATFORMS[platform]
            entity_ref=None
            if platform=='zhihu':entity_ref='zhihu:content:'+payload['content_id']+':'+candidates[0]['content_type']
            elif len(candidates)==1 and candidates[0]['kind']=='dynamic':entity_ref=platform+':dynamic:'+payload['content_id']
            if payload['kind']=='video_ocr':
                region=payload.get('text_region','bottom');regions={'bottom':(.67,.82),'top':(.12,.32),'full':(0.,1.)}
                if action!='start' or not isinstance(region,str) or region not in regions or source.suffix.lower()!='.mp4':raise ValueError('invalid_video_ocr_request')
                folder=self._registered_run_root(payload['run_id'])/'runs'/payload['run_id']
                return self.media_jobs.start_saved_video_ocr(folder,source,platform,payload['content_id'],entity_ref=entity_ref,crop_top=regions[region][0],crop_bottom=regions[region][1])
            options={'entity_ref':entity_ref}
            if action=='start' and 'speech_check' in payload:options['speech_check']=payload['speech_check']
            if action == 'start' and payload['kind'] == 'asr' and 'asr_engine' in payload:
                options['asr_engine'] = payload['asr_engine']
            if payload['kind']=='asr' and source.suffix.lower()=='.mp4':options['native_run_folder']=self._registered_run_root(payload['run_id'])/'runs'/payload['run_id']
            return getattr(self.media_jobs,action)(source,platform,payload['content_id'],payload['kind'],payload['run_id'],**options)
        raise ValueError('invalid_media_processing_action')


def make_server(app, port=45937):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # No task targets, local paths or source records in HTTP logs.

        def allowed_host(self):
            expected = str(self.server.server_port)
            return self.headers.get('Host') in ('127.0.0.1:' + expected, 'localhost:' + expected)

        def send(self, value, code=200, html=False):
            data = value.encode() if html else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-" + app.token + "'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self'; media-src blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed_host():
                return self.send({'ok': False, 'error': 'host_rejected'}, 403)
            path = urlsplit(self.path).path
            if path == '/':
                document = (HERE / 'dashboard.html').read_text()
                return self.send(document.replace('__NONCE__', app.token), html=True)
            if path in ('/analysis-ui.js', '/owner-ui.js', '/results-ui.js', '/media-ui.js', '/accounts-ui.js', '/cloud-ui.js', '/fleet-ui.js'):
                data = (HERE / path[1:]).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/javascript; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
                return
            if path == '/api/config':
                return self.send({'ok': True, 'mc_root': app.mc_root})
            return self.send({'ok': False, 'error': 'not_found'}, 404)

        def do_POST(self):
            expected = {'http://127.0.0.1:' + str(self.server.server_port), 'http://localhost:' + str(self.server.server_port)}
            if not self.allowed_host() or self.headers.get('Origin') not in expected or not secrets.compare_digest(self.headers.get('X-Crowd-CSRF', ''), app.token):
                return self.send({'ok': False, 'error': 'local_origin_required'}, 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                limit = 131072 if self.path == '/api/cloud' else 32768
                if not 0 < length <= limit or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('invalid_request')
                body = json.loads(self.rfile.read(length))
                if (not isinstance(body, dict) or length > 32768 and
                        (self.path != '/api/cloud' or body.get('action') != 'retry_delivery')):
                    raise ValueError('invalid_request')
                if self.path == '/api/config':
                    return self.send(app.configure(body))
                if self.path == '/api/cloud':
                    if set(body) != {'action', 'payload'}:
                        raise ValueError('invalid_cloud_request')
                    return self.send(app.cloud(body['action'], body['payload']))
                if self.path == '/api/health':
                    if body != {'action': 'status', 'payload': {}}:
                        raise ValueError('invalid_health_request')
                    return self.send(app.health())
                if self.path == '/api/analysis':
                    if set(body) != {'action', 'payload'}:
                        raise ValueError('invalid_analysis_request')
                    return self.send(app.analysis(body['action'], body['payload']))
                if self.path == '/api/tasks':
                    if set(body) != {'action', 'payload'}:
                        raise ValueError('invalid_task_request')
                    return self.send(app.tasks(body['action'], body['payload']))
                if self.path == '/api/watchlists':
                    if set(body) != {'action', 'payload'}:
                        raise ValueError('invalid_watchlist_request')
                    return self.send(app.watches(body['action'], body['payload']))
                if self.path == '/api/accounts':
                    if set(body) != {'action', 'payload'}:
                        raise ValueError('invalid_account_request')
                    return self.send(app.accounts(body['action'], body['payload']))
                if self.path == '/api/results':
                    if set(body) != {'action', 'payload'}:
                        raise ValueError('invalid_results_request')
                    value = app.results(body['action'], body['payload'])
                    if body['action'] == 'export':
                        data = value['data']
                        self.send_response(200)
                        self.send_header('Content-Type', value['mime'])
                        self.send_header('Content-Length', str(len(data)))
                        self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(value['filename']))
                        self.send_header('X-Content-SHA256', value['sha256'])
                        self.send_header('X-Crowd-Export-Manifest', base64.urlsafe_b64encode(json.dumps(value['manifest'], ensure_ascii=False).encode()).decode())
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    return self.send(value)
                if self.path == '/api/media-processing':
                    if set(body) != {'action', 'payload'}:
                        raise ValueError('invalid_media_processing_request')
                    if body['action'] in ('playback', 'video_file', 'video_cloud_file', 'native_video_cloud_file'):
                        value = app.process_media(body['action'], body['payload'])
                        self.send_response(200)
                        self.send_header('Content-Type', value['mime'])
                        self.send_header('Content-Length', str(len(value['data'])))
                        self.send_header('X-Content-SHA256', value['sha256'])
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        self.wfile.write(value['data'])
                        return
                    return self.send(app.process_media(body['action'], body['payload']))
                if self.path in ('/api/media', '/api/artifact'):
                    path = app.media_file(body, artifact=self.path == '/api/artifact')
                    with path.open('rb') as stream:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(os.fstat(stream.fileno()).st_size))
                        self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(path.name))
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.end_headers()
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
                if self.path != '/api/action' or set(body) != {'action', 'payload'}:
                    raise ValueError('invalid_request')
                if body['action']=='stop':
                    if not isinstance(body['payload'],dict) or set(body['payload'])!={'run_id'}:
                        raise ValueError('invalid_stop_request')
                    body['payload']={**body['payload'],'origin':'user','reason':'user_stop'}
                return self.send(app.run(body['action'], body['payload']))
            except sqlite3.Error:
                return self.send({'ok': False, 'error': 'local_storage_unavailable'}, 503)
            except (ValueError, TypeError, OSError) as error:
                message = str(error)
                return self.send({'ok': False, 'error': message if message.replace('_', '').isalnum() else 'invalid_request'}, 400)

    class Server(ThreadingHTTPServer):
        def server_close(self):
            app.health_events.close()
            if app.analysis_jobs is not None:
                app.analysis_jobs.close()
            app.watchlists.close()
            if app.owner_tasks is not None:
                app.owner_tasks.close()
            if app.cloud_worker is not None:
                app.cloud_worker.close()
            if app.media_jobs is not None:
                app.media_jobs.close()
            super().server_close()

    return Server(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'Library/Application Support/CrowdCollector')
    parser.add_argument('--mc-root')
    parser.add_argument('--collector-root', action='append', type=Path, default=[],
                        help='Register an existing runs/sessions root without moving it; repeatable')
    parser.add_argument('--port', type=int, default=45937)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    server = make_server(Application(args.root, args.mc_root, args.collector_root), args.port)
    url = 'http://127.0.0.1:' + str(server.server_port)
    print('多平台采集工作台：' + url, flush=True)
    print('关闭此终端只关闭工作台；请先在页面停止仍在运行的采集任务。', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

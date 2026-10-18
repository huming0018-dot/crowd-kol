"""Finite run failure diagnostics; never transports an exception or arbitrary text."""
PHASES=frozenset(('importing','delivering','finishing','completed','waiting_login','paused'))
ERROR_CODES=frozenset(('login_required', 'native_provider_browser_unavailable', 'native_provider_busy', 'native_provider_cleanup_unknown', 'native_provider_cookie_scope_invalid', 'native_provider_cookie_shape_invalid', 'native_provider_credentials_unavailable', 'native_provider_exit_observer_unavailable', 'native_provider_lock_invalid', 'native_provider_mc_missing', 'native_provider_ownership_lost', 'native_provider_persistence_unavailable', 'native_provider_profile_busy', 'native_provider_profile_invalid', 'native_provider_profile_missing', 'native_provider_profile_mode_unverified', 'native_provider_retry_forbidden', 'native_provider_session_invalid', 'native_provider_unavailable', 'phase_observation_failed', 'pro_account_changed', 'pro_bili_wbi_unavailable', 'pro_content_access_denied', 'pro_cookiebridge_unavailable', 'pro_existing_cdp_credentials_unavailable', 'pro_login_verification_failed', 'pro_native_credentials_unavailable', 'pro_self_check_unsupported', 'pro_signer_source_changed', 'pro_signer_wrapper_changed', 'pro_weibo_reply_target_invalid', 'run_completed', 'run_failure_unclassified', 'run_outcome_unknown', 'run_stopped', 'wb_checkpoint_binding', 'wb_checkpoint_unconfirmed', 'wb_comment_identity_invalid', 'wb_comment_limit_state_invalid', 'wb_comment_parent_invalid', 'wb_comment_replayed', 'wb_cursor_stalled', 'wb_embedded_replies_incomplete', 'wb_operation_unsupported', 'wb_page_budget', 'wb_page_budget_invalid', 'wb_page_cursor_invalid', 'wb_page_evidence_limit', 'wb_page_file_binding', 'wb_page_file_invalid', 'wb_partial_page_requires_resolution', 'wb_protocol_mapping_conflict', 'wb_reply_business_code_invalid', 'wb_reply_count_invalid', 'wb_reply_cursor_invalid', 'wb_reply_cursor_stalled', 'wb_reply_http_invalid', 'wb_reply_nested_shape_unverified', 'wb_reply_page_budget', 'wb_reply_page_shape_invalid', 'wb_reply_parent_invalid', 'wb_reply_target_invalid', 'wb_reply_target_unbound', 'wb_reply_terminal_incomplete', 'wb_reply_transport_contract_invalid', 'wb_resume_cursor_type_unverified', 'wb_save_failed', 'wb_save_not_durable'))
NATIVE_CODES=frozenset(('native_provider_browser_unavailable', 'native_provider_busy', 'native_provider_cleanup_unknown', 'native_provider_cookie_scope_invalid', 'native_provider_cookie_shape_invalid', 'native_provider_credentials_unavailable', 'native_provider_exit_observer_unavailable', 'native_provider_lock_invalid', 'native_provider_mc_missing', 'native_provider_ownership_lost', 'native_provider_persistence_unavailable', 'native_provider_profile_busy', 'native_provider_profile_invalid', 'native_provider_profile_missing', 'native_provider_profile_mode_unverified', 'native_provider_retry_forbidden', 'native_provider_session_invalid', 'native_provider_unavailable'))

def validate(value,phase):
 if not isinstance(value,dict) or set(value)-{'error_code','exit_code'} or phase not in PHASES:
  raise ValueError('invalid_run_diagnostic')
 code=value.get('error_code')
 if type(code) is not str or code not in ERROR_CODES:raise ValueError('invalid_run_diagnostic')
 if 'exit_code' in value and (type(value['exit_code']) is not int or not -128<=value['exit_code']<=255):
  raise ValueError('invalid_run_diagnostic')
 return dict(value)

def from_status(status):
 if not isinstance(status,dict):return None
 state=status.get('state')
 if state not in ('completed','failed','stopped','interrupted','interrupted_unknown','login_required'):return None
 code={'completed':'run_completed','stopped':'run_stopped','interrupted':'run_outcome_unknown','interrupted_unknown':'run_outcome_unknown','login_required':'login_required'}.get(state)
 if code is None:
  code=next((status[k] for k in ('failure_reason','reason') if type(status.get(k)) is str and status[k] in ERROR_CODES),'run_failure_unclassified')
  if code in ('pro_native_credentials_unavailable','pro_existing_cdp_credentials_unavailable') and status.get('credential_provider') in ('native_persistent','existing_cdp'):
   detail=status.get('credential_reason')
   if type(detail)is str and detail in NATIVE_CODES:code=detail
 result={'error_code':code};exit_code=status.get('exit_code')
 if type(exit_code) is int and -128<=exit_code<=255:result['exit_code']=exit_code
 return result

"""Known local saved-record refusal; never infer a source outcome from an exception."""
PERMANENT_REJECTIONS = frozenset({
    'existing_saved_reader_missing', 'existing_saved_selection_mismatch',
    'existing_saved_target_mismatch', 'existing_saved_target_unverified',
    'invalid_results_revision', 'results_version_not_found',
    'invalid_results_version', 'existing_saved_selection_unavailable',
})


def rejected_before_dispatch(state, code, stats):
    """Only an authorized saved-only run with no staged rows may finish failed/zero."""
    return (code in PERMANENT_REJECTIONS
            and state.get('phase') == 'authorized'
            and state.get('local_run_id') is None
            and (state.get('lease') or {}).get('delivery_basis') == 'existing_saved'
            and stats.get('capture_ids') == []
            and all(type(stats.get(name)) is int and stats[name] == 0
                    for name in ('pending', 'acknowledged', 'quarantined')))

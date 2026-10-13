"""Account for native Tieba browser fetches without copying cookies or responses."""
from pathlib import Path
from mc_runner import read, write


def install(client_class, run_dir, debit):
    original = client_class._fetch_json_by_browser
    run_dir = Path(run_dir)

    async def fetch(self, uri, *args, **kwargs):
        debit()  # Native SDK uses page.evaluate(fetch), outside httpx.send.
        endpoint = {'/c/s/pc/sync': 'session_sync', '/c/f/pb/page_pc': 'post_detail'}.get(uri, 'other_native_api')

        def record(state):
            path = run_dir / 'phase.json'
            phase = read(path) if path.exists() else {}
            write(path, {**phase, 'tieba_browser_request': {'endpoint': endpoint, 'state': state,
                'reason': 'tieba_native_browser_request_failed' if state == 'failed' else None}})

        record('dispatch_unknown')
        try:
            result = await original(self, uri, *args, **kwargs)
        except Exception:
            record('failed')
            raise
        record('returned')
        return result

    client_class._fetch_json_by_browser = fetch

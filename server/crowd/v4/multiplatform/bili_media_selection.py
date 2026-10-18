"""Process-local audio selection from an already received native DASH response."""

from typing import Callable, Optional


def _positive_integer(value):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 19:
        number = int(value)
    else:
        return None
    return number if 0 < number <= 2**63 - 1 else None


def install_low_audio_selection(native_media, quality, phase_callback: Optional[Callable] = None) -> bool:
    """Only explicit q16 changes audio; native download/merge and other qualities stay intact."""
    current = native_media.pick_audio_stream
    original = getattr(current, "_crowd_original_audio_selector", current)
    if not callable(original):
        raise ValueError("native_audio_selector_required")
    if type(quality) is not int or quality != 16:
        native_media.pick_audio_stream = original
        return False

    def select(play_info):
        dash = play_info.get("dash") if isinstance(play_info, dict) else None
        rows = dash.get("audio") if isinstance(dash, dict) else None
        eligible = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                stream_id = _positive_integer(row.get("id"))
                bandwidth = _positive_integer(row.get("bandwidth"))
                url = row.get("base_url") or row.get("baseUrl")
                if stream_id is not None and bandwidth is not None and isinstance(url, str) and url:
                    eligible.append((bandwidth, stream_id, row))
        chosen = min(eligible, key=lambda entry: (entry[0], entry[1]))[2] if eligible else original(play_info)
        if phase_callback is not None:
            phase_callback({
                "selection": "lowest_positive_bandwidth_native_audio" if eligible else "native_default_no_bounded_candidate",
                "native_stream_id": _positive_integer(chosen.get("id")) if isinstance(chosen, dict) else None,
                "bandwidth": _positive_integer(chosen.get("bandwidth")) if isinstance(chosen, dict) else None,
                "eligible_audio_streams": len(eligible),
            })
        return chosen

    select._crowd_original_audio_selector = original
    native_media.pick_audio_stream = select
    return True

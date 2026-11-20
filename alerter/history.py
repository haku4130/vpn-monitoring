import statistics
from datetime import datetime, timezone

from summary import is_divider, key_name

HOURS_KEPT = 25
HOUR = 3600


def hour_key(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H")


def _hours(state):
    return state.setdefault("history", {"hours": {}}).setdefault("hours", {})


def _bucket(state, ts):
    return _hours(state).setdefault(hour_key(ts), {"rows": {}, "lat": {}})


def touch(state, ts, key, alerted):
    row = _bucket(state, ts)["rows"].setdefault(key, [0, 0])
    row[1] = 1 if (row[1] or alerted) else 0


def add_fail(state, ts, key):
    touch(state, ts, key, False)
    _bucket(state, ts)["rows"][key][0] += 1


def add_latency(state, ts, key, ms):
    _bucket(state, ts)["lat"].setdefault(key, []).append(ms)


def prune(state, ts):
    hours = _hours(state)
    oldest = hour_key(ts - HOURS_KEPT * HOUR)
    for h in [h for h in hours if h <= oldest]:
        del hours[h]


def day_window(end_ts):
    base = end_ts - end_ts % HOUR
    return [hour_key(base - n * HOUR) for n in range(24, 0, -1)]


def _cell(fails, alerted):
    if alerted:
        return "alert"
    if fails >= 2:
        return "many"
    if fails == 1:
        return "one"
    return "clean"


def heat_rows(state, end_ts):
    hours = _hours(state)
    window = day_window(end_ts)
    merged = {}
    for i, h in enumerate(window):
        for key, (fails, alerted) in hours.get(h, {}).get("rows", {}).items():
            name = key_name(key)
            if is_divider(name):
                continue
            row = merged.setdefault(name, {})
            f, a = row.get(i, (0, 0))
            row[i] = (f + fails, a or alerted)
    return {
        name: [_cell(*row[i]) if i in row else "nodata" for i in range(len(window))]
        for name, row in merged.items()
    }


def latency_medians(state, end_ts):
    hours = _hours(state)
    values = {}
    for h in day_window(end_ts):
        for key, ms in hours.get(h, {}).get("lat", {}).items():
            name = key_name(key)
            if not is_divider(name):
                values.setdefault(name, []).extend(ms)
    return {name: statistics.median(v) for name, v in values.items() if v}

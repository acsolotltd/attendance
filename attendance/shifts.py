"""Shift logic for fixed and rotating day/night shifts. Django-free so it can be unit-tested.

A shift is a dict: {"id", "name", "start": time, "end": time, "days": {0..6, Mon=0}, "grace": min,
                    "ot_after": min, "before": min, "after": min, "is_default": bool}
A shift that ends at or before its start time runs past midnight (night shift).
`resolve(user_id, day)` returns the shift a user works on `day` (the day the shift STARTS) or None.
"""
from collections import defaultdict
from datetime import datetime, timedelta

MIN_SPAN = timedelta(minutes=10)  # two punches closer than this are one tap (in OR out), not in + out


def uid_key(uid):
    return (0, int(uid), "") if str(uid).isdigit() else (1, 0, str(uid))


def rotation_blocks(start, end, weeks=1):
    """Splits start..end into blocks of `weeks` weeks: [(block_start, block_end, index)]."""
    blocks, cur, i = [], start, 0
    while cur <= end:
        nxt = cur + timedelta(weeks=max(1, weeks))
        blocks.append((cur, min(nxt - timedelta(days=1), end), i))
        cur, i = nxt, i + 1
    return blocks


def instance_times(shift, day):
    """(start, end, window_start, window_end) of the shift that begins on `day`."""
    s = datetime.combine(day, shift["start"])
    e = datetime.combine(day, shift["end"])
    if e <= s:
        e += timedelta(days=1)
    return s, e, s - timedelta(minutes=shift["before"]), e + timedelta(minutes=shift["after"])


def _minutes(delta):
    return int(delta.total_seconds() // 60)


def _row(uid, name, day, shift, punches):
    s, e, _, _ = instance_times(shift, day)
    first, last = punches[0], punches[-1]
    row = {"date": day, "uid": uid, "name": name, "shift": shift["name"], "sched_in": s, "sched_out": e,
           "in": first, "out": last, "late_min": 0, "early_min": 0, "ot_min": 0, "hours": None, "status": ""}
    grace = timedelta(minutes=shift["grace"])
    flags = []
    if len(punches) == 1 or last - first < MIN_SPAN:
        if first <= s + (e - s) / 2:                    # a lone punch in the first half = check-in only
            row["out"] = None
            flags.append("Missing check-out")
        else:                                            # in the second half = check-out only
            row["in"] = None
            flags.append("Missing check-in")
    else:
        row["hours"] = round((last - first).total_seconds() / 3600, 2)
    if row["in"] and row["in"] > s + grace:
        row["late_min"] = _minutes(row["in"] - s)
        flags.append("Late")
    if row["out"]:
        if row["out"] < e - grace:
            row["early_min"] = _minutes(e - row["out"])
            flags.append("Early leave")
        elif row["out"] - e >= timedelta(minutes=shift["ot_after"]):
            row["ot_min"] = _minutes(row["out"] - e)
            flags.append("Overtime")
    row["status"] = ", ".join(flags) or "On time"
    return row


def build_shift_report(records, resolve, start, end, extra_users=(), names=None, now=None):
    """records: punch dicts (user_id, name, timestamp). Pass punches from start-1 to end+1 so shifts that
    cross midnight at the edges are complete. Returns (rows, stats); only shifts STARTING in start..end."""
    now = now or datetime.now()
    names = dict(names or {})
    by_user = defaultdict(list)
    for r in records:
        by_user[r["user_id"]].append(r)
        if r.get("name"):
            names[r["user_id"]] = r["name"]

    instances, unmatched = {}, 0
    for uid, recs in by_user.items():
        for r in recs:
            ts, best = r["timestamp"], None
            for off in (-1, 0, 1):
                day = ts.date() + timedelta(days=off)
                shift = resolve(uid, day)
                if not shift:
                    continue
                s, e, ws, we = instance_times(shift, day)
                if not ws <= ts <= we:
                    continue
                dist = 0 if s <= ts <= e else min(abs((ts - s).total_seconds()), abs((ts - e).total_seconds()))
                if best is None or dist < best[0]:
                    best = (dist, day, shift)
            if best:
                instances.setdefault((uid, best[1]), {"shift": best[2], "punches": []})["punches"].append(ts)
            else:
                unmatched += 1

    rows = [_row(uid, names.get(uid, ""), day, inst["shift"], sorted(inst["punches"]))
            for (uid, day), inst in instances.items() if start <= day <= end]

    span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    for uid in set(by_user) | set(extra_users):
        for day in span:
            shift = resolve(uid, day)
            if shift and day.weekday() in shift["days"] and (uid, day) not in instances:
                s, e, _, _ = instance_times(shift, day)
                if s <= now:                              # don't mark future / not-yet-started shifts absent
                    rows.append({"date": day, "uid": uid, "name": names.get(uid, ""), "shift": shift["name"],
                                 "sched_in": s, "sched_out": e, "in": None, "out": None, "late_min": 0,
                                 "early_min": 0, "ot_min": 0, "hours": None, "status": "Absent"})
    rows.sort(key=lambda r: (r["date"], r["sched_in"], uid_key(r["uid"])))
    no_shift = sorted((u for u in by_user if all(resolve(u, d) is None for d in span)), key=uid_key)
    return rows, {"unmatched_punches": unmatched, "users_without_shift": no_shift}


def totals(rows):
    out = {}
    for r in rows:
        t = out.setdefault(r["uid"], {"uid": r["uid"], "name": r["name"], "shifts": 0, "absent": 0, "late_count": 0,
                                      "late_min": 0, "early_count": 0, "early_min": 0, "ot_min": 0, "hours": 0.0})
        t["name"] = t["name"] or r["name"]
        if r["status"] == "Absent":
            t["absent"] += 1
            continue
        t["shifts"] += 1
        t["late_count"] += 1 if r["late_min"] else 0
        t["late_min"] += r["late_min"]
        t["early_count"] += 1 if r["early_min"] else 0
        t["early_min"] += r["early_min"]
        t["ot_min"] += r["ot_min"]
        t["hours"] += r["hours"] or 0
    result = sorted(out.values(), key=lambda t: uid_key(t["uid"]))
    for t in result:
        t["hours"] = round(t["hours"], 2)
    return result

"""Database-backed helpers: local copy of punches, sync, ADMS ingestion and reading from the copy."""
import datetime as dt

from django.utils import timezone

from . import services
from .models import AttendanceLog, Device, DeviceRequestLog, DeviceUser, Shift


def device_address(device):
    return f"ADMS · {device.serial_number}" if device.mode == "adms" else f"{device.ip_address}:{device.port}"


def save_records(device, records):
    """Stores punches not stored yet (unique on device+user+timestamp). Returns how many were new."""
    if not records:
        return 0
    lo, hi = min(r["timestamp"] for r in records), max(r["timestamp"] for r in records)
    have = set(AttendanceLog.objects.filter(device=device, timestamp__gte=lo, timestamp__lte=hi)
               .values_list("user_id", "timestamp"))
    fresh, seen = [], set()
    for r in records:
        key = (r["user_id"], r["timestamp"])
        if key not in have and key not in seen:
            seen.add(key)
            fresh.append(AttendanceLog(device=device, user_id=r["user_id"], name=r["name"], timestamp=r["timestamp"],
                                       punch=r["punch_code"], verify=r["verify_code"]))
    # ignore_conflicts still guards against two uploads racing each other
    AttendanceLog.objects.bulk_create(fresh, ignore_conflicts=True, batch_size=500)
    return len(fresh)


def save_users(device, users):
    """Stores PIN->name pairs; back-fills names on stored punches only for new or renamed users."""
    existing = {u.pin: u for u in DeviceUser.objects.filter(device=device)}
    new, changed, touched = [], [], []
    for pin, name in users:
        row = existing.get(pin)
        if row is None:
            new.append(DeviceUser(device=device, pin=pin, name=name))
            existing[pin] = new[-1]
            touched.append((pin, name))
        elif row.name != name:
            row.name = name
            changed.append(row)
            touched.append((pin, name))
    DeviceUser.objects.bulk_create(new, ignore_conflicts=True)
    if changed:
        DeviceUser.objects.bulk_update(changed, ["name"])
    for pin, name in touched:
        AttendanceLog.objects.filter(device=device, user_id=pin).exclude(name=name).update(name=name)
    return len(users)


def ingest_attlog(device, records):
    """ADMS punches -> local database, with names resolved from known users. Returns new rows saved."""
    names = dict(DeviceUser.objects.filter(device=device).values_list("pin", "name"))
    for r in records:
        r["name"] = names.get(r["user_id"], "")
    return save_records(device, records)


def log_request(request, serial, body, response, remote_ip):
    entry = DeviceRequestLog.objects.create(
        serial=serial[:64], method=request.method[:8], path=request.get_full_path()[:500],
        body_preview=body[:1500], response_preview=response.content.decode("utf-8", "replace")[:300],
        status=response.status_code, remote_ip=remote_ip[:45])
    if entry.pk % 20 == 0:  # keep only the latest ~300 requests
        stale = list(DeviceRequestLog.objects.order_by("-id").values_list("id", flat=True)[300:])
        if stale:
            DeviceRequestLog.objects.filter(id__in=stale).delete()


def fetch_live(devices, start, end, user_query="", save=True):
    """Pull mode: downloads from devices; optionally stores the device's COMPLETE log (not just the range)."""
    devices = list(devices)
    tokens = services.parse_user_filter(user_query)
    records, summary = services.fetch_all(devices, start, end, tokens, keep_all=save)
    for device, meta in zip(devices, summary):
        everything = meta.pop("all_records", None)
        if not save or meta["error"] or everything is None:
            continue
        meta["new_saved"] = save_records(device, everything)
        device.last_sync_at = timezone.now()
        device.save(update_fields=["last_sync_at"])
    return records, summary


def load_records(devices, start, end, user_query=""):
    devices = list(devices)
    tokens = services.parse_user_filter(user_query)
    qs = (AttendanceLog.objects
          .filter(device__in=devices,
                  timestamp__gte=dt.datetime.combine(start, dt.time.min),
                  timestamp__lte=dt.datetime.combine(end, dt.time.max))
          .select_related("device").order_by("timestamp", "user_id"))
    counts = {d.pk: 0 for d in devices}
    records = []
    for row in qs.iterator(chunk_size=2000):
        if tokens and not services.matches_user(tokens, row.user_id, row.name):
            continue
        records.append({
            "device": row.device.name, "user_id": row.user_id, "name": row.name, "timestamp": row.timestamp,
            "punch": "Punch" if row.device.punch_state_unused else services.label(services.PUNCH_LABELS, row.punch),
            "punch_code": row.punch,
            "verify": services.label(services.VERIFY_LABELS, row.verify), "verify_code": row.verify,
        })
        counts[row.device_id] += 1
    summary = [{"name": d.name, "address": device_address(d), "count": counts[d.pk], "on_device": 0,
                "duplicates": 0, "error": None, "elapsed": 0, "source": "adms" if d.mode == "adms" else "database"}
               for d in devices]
    return records, summary


def collect(devices, start, end, user_query="", source="live", save=True):
    """One entry point for both modes. ADMS devices always read from the database (they push into it)."""
    devices = list(devices)
    pull = [d for d in devices if d.mode == "pull"]
    adms_devices = [d for d in devices if d.mode == "adms"]
    records, summary = [], []
    if pull:
        if source == "db":
            r, s = load_records(pull, start, end, user_query)
        else:
            r, s = fetch_live(pull, start, end, user_query, save=save)
        records += r
        summary += s
    if adms_devices:
        r, s = load_records(adms_devices, start, end, user_query)
        records += r
        summary += s
    records.sort(key=lambda r: (r["timestamp"], r["device"], r["user_id"]))
    return records, summary


def _ago(then):
    secs = int((dt.datetime.now() - then).total_seconds())
    if secs < 90:
        return f"{secs}s ago"
    if secs < 5400:
        return f"{secs // 60} min ago"
    return f"{secs // 3600} h ago"


def adms_info(device):
    """Details panel for an ADMS device (what the server knows; the device itself is never contacted)."""
    online, _ = services.probe(device)
    rows = [("Mode", "ADMS / push"), ("Serial number", device.serial_number or "n/a"),
            ("Status", "Online" if online else "Offline"),
            ("Last seen", f"{device.last_seen:%Y-%m-%d %H:%M:%S} ({_ago(device.last_seen)})"
             if device.last_seen else "never"),
            ("Last IP", device.last_ip or "n/a"), ("Stored punches", device.logs.count()),
            ("Known users", device.users.count()), ("Punch sync position", device.att_stamp)]
    for key, value in list((device.device_info or {}).items())[:12]:
        rows.append((key, value))
    note = ""
    if not device.last_seen:
        note = ("This device has never contacted the server. On the device open Menu > Comm. > Cloud Server "
                "Setting, enter this server's address and port, then watch Device activity below.")
    elif not online:
        note = (f"No contact for {_ago(device.last_seen)[:-4]}. Check the device's power/network and its "
                "Cloud Server Setting.")
    commands = []
    for c in device.commands.order_by("-id")[:5]:
        state = "queued" if c.sent_at is None else ("sent, waiting for reply" if c.finished_at is None
                                                    else f"done (return {c.result_code})")
        commands.append({"id": c.pk, "command": c.command, "state": state})
    return {"ok": True, "rows": rows, "note": note, "elapsed": 0.0, "commands": commands}


# --------------------------------------------------------------------------- shifts

def make_shift_resolver():
    """Returns (resolve(user_id, day) -> shift dict | None, set of assigned user ids)."""
    from collections import defaultdict
    from .models import Shift, ShiftAssignment
    shifts_by_id = {s.pk: s.as_dict() for s in Shift.objects.all()}
    default = next((s for s in shifts_by_id.values() if s["is_default"]), None)
    assigned = defaultdict(list)
    for a in ShiftAssignment.objects.order_by("-id"):  # newest assignment wins
        assigned[a.user_id].append((a.start_date, a.end_date, shifts_by_id.get(a.shift_id)))

    def resolve(user_id, day):
        for start, end, shift in assigned.get(user_id, ()):
            if shift and start <= day and (end is None or day <= end):
                return shift
        return default

    return resolve, set(assigned)


def build_shift_report(records, start, end, user_query="", devices=None):
    """records must include one extra day on each side of start..end (see views._build)."""
    from . import shifts
    resolve, assigned = make_shift_resolver()
    names = dict(DeviceUser.objects.filter(device__in=devices).values_list("pin", "name")) if devices else {}
    known = assigned | set(names)
    tokens = services.parse_user_filter(user_query)
    if tokens:
        known = {u for u in known if services.matches_user(tokens, u, names.get(u, ""))}
    return shifts.build_shift_report(records, resolve, start, end, extra_users=known, names=names)



# --------------------------------------------------------------------------- dashboard helpers

def pending_serials(hours=1):
    """Serial numbers that called in recently but are not registered (refused with 403)."""
    since = timezone.now() - dt.timedelta(hours=hours)
    known = set(Device.objects.exclude(serial_number="").values_list("serial_number", flat=True))
    seen = {}
    rows = (DeviceRequestLog.objects.filter(status=403, created_at__gte=since).exclude(serial="")
            .values_list("serial", "remote_ip"))
    for serial, ip in rows:
        if serial not in known:
            seen.setdefault(serial, ip)
    return [{"serial": s, "ip": ip} for s, ip in seen.items()]


def dashboard_stats():
    start = dt.datetime.combine(dt.date.today(), dt.time.min)
    devices = list(Device.objects.all())
    adms = [d for d in devices if d.mode == "adms"]
    return {
        "devices": len(devices), "adms": len(adms), "pull": len(devices) - len(adms),
        "adms_online": sum(1 for d in adms if services.probe(d)[0]),
        "punches_today": AttendanceLog.objects.filter(timestamp__gte=start).count(),
        "punches_total": AttendanceLog.objects.count(),
        "last_punch": AttendanceLog.objects.order_by("-timestamp").values_list("timestamp", flat=True).first(),
        "shifts": Shift.objects.count(),
    }

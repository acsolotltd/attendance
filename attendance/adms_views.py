"""Endpoints the DEVICE calls (ADMS / push protocol). No login: devices cannot authenticate.

Hardening: optional IP allow-list, per-IP rate limit, unknown serials refused (403) until registered,
bodies of binary uploads (photos/templates) acknowledged but never stored or journaled.
"""
import ipaddress
import logging
import secrets
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import adms, store
from .models import Device, DeviceCommand

logger = logging.getLogger(__name__)
BINARY_TABLES = {"ATTPHOTO", "BIOPHOTO", "USERPIC", "FINGERTMP", "BIODATA", "TEMPLATEV10", "FACE", "FPTEMPLATE"}


def _text(body, status=200):
    return HttpResponse(body, content_type="text/plain", status=status)


def client_ip(request):
    if getattr(settings, "TRUST_PROXY_HEADERS", False):  # X-Forwarded-For is only believed behind our own proxy
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.META.get("REMOTE_ADDR", "")


def _ip_allowed(request):
    networks = getattr(settings, "ADMS_ALLOWED_NETWORKS", [])
    if not networks:
        return True
    try:
        ip = ipaddress.ip_address(client_ip(request))
    except ValueError:
        return False
    return any(ip in net for net in networks)


def _rate_limited(request):
    limit = getattr(settings, "ADMS_RATE_LIMIT_PER_MIN", 0)
    if not limit:
        return False
    key = f"adms-rl:{client_ip(request)}:{int(timezone.now().timestamp() // 60)}"
    cache.add(key, 0, 90)
    try:
        return cache.incr(key) > limit
    except ValueError:
        return False


def adms_endpoint(view):
    """csrf-exempt + guards + request journal + safe error handling (a 500 makes the device retry later)."""
    @csrf_exempt
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not _ip_allowed(request):
            return _text("ERROR: forbidden", 403)          # not journaled: nothing to learn from strangers
        if _rate_limited(request):
            return _text("ERROR: slow down", 429)
        body, preview = "", ""
        try:
            if request.method == "POST":
                raw = request.body
                if request.GET.get("table", "").upper() in BINARY_TABLES or request.path.endswith("/fdata"):
                    preview = f"[{len(raw)} bytes of binary data, acknowledged and not stored]"
                else:
                    body = preview = adms.decode_body(raw)
            response = view(request, body, *args, **kwargs)
        except RequestDataTooBig:
            response = _text("ERROR: body too large", 413)
        except Exception:
            logger.exception("ADMS request failed: %s", request.get_full_path())
            response = _text("ERROR", 500)
        heartbeat = (request.path.endswith("/getrequest") and response.status_code == 200 and response.content == b"OK")
        if not heartbeat or getattr(settings, "ADMS_LOG_HEARTBEATS", False):
            try:
                serial = request.GET.get("SN") or request.GET.get("sn") or ""
                store.log_request(request, serial, preview, response, client_ip(request))
            except Exception:
                logger.exception("could not journal ADMS request")
        return response
    return wrapper


def _device_for(request):
    sn = (request.GET.get("SN") or request.GET.get("sn") or "").strip()
    if not adms.valid_serial(sn):
        return None, _text("ERROR: missing or invalid SN", 400)
    device = Device.objects.filter(serial_number=sn).first()
    if device is None:
        if not getattr(settings, "ADMS_AUTO_REGISTER", False):
            return None, _text("ERROR: unknown device", 403)  # device keeps its backlog and retries later
        device, _ = Device.objects.get_or_create(serial_number=sn, defaults={"name": f"ADMS {sn}", "mode": "adms"})
    device.last_seen = timezone.now()
    device.last_ip = client_ip(request)[:45]
    device.save(update_fields=["last_seen", "last_ip"])
    return device, None


def _remember(device, values):
    info = dict(device.device_info or {})
    for k, v in values.items():
        if k.lower() in ("id", "return", "cmd", "sn", "table", "stamp", "options") or not v:
            continue
        if len(info) < 60 or k in info:
            info[k] = v
    if info != (device.device_info or {}):
        device.device_info = info
        device.save(update_fields=["device_info"])


def _store_punches(device, records, skipped, body, stamp):
    """Returns an error response if the batch was unusable (so the device keeps and re-sends it), else None."""
    if body.strip() and not records:
        return _text("ERROR: could not parse punches", 400)  # never acknowledge what we could not read
    if skipped:
        logger.warning("%s: skipped %s unparseable punch lines", device.serial_number, skipped)
    store.ingest_attlog(device, records)
    if stamp:
        device.att_stamp = stamp
        device.save(update_fields=["att_stamp"])
    return None


@adms_endpoint
def cdata(request, body):
    device, error = _device_for(request)
    if error:
        return error
    if request.method == "GET":  # handshake
        _remember(device, {k: request.GET.get(k, "") for k in ("pushver", "language", "PushOptionsFlag")})
        return _text(adms.handshake_response(
            device.serial_number, device.att_stamp, device.oper_stamp, delay=getattr(settings, "ADMS_DELAY", 30),
            trans_flag=adms.trans_flag_for(device.trans_profile, getattr(settings, "ADMS_TRANS_FLAG", ""))))

    table = (request.GET.get("table") or "").upper()
    stamp = (request.GET.get("Stamp") or request.GET.get("stamp") or "")[:32]
    if table == "ATTLOG":
        records, skipped = adms.parse_attlog(body)
        error = _store_punches(device, records, skipped, body, stamp)
        if error:
            return error
    elif table in ("OPERLOG", "USERINFO", "USER"):
        store.save_users(device, adms.parse_users(body))
        op_stamp = (request.GET.get("OpStamp") or stamp)[:32]
        if op_stamp and table == "OPERLOG":
            device.oper_stamp = op_stamp
            device.save(update_fields=["oper_stamp"])
    elif table == "TABLEDATA":  # push 3.x: generic table upload
        name = (request.GET.get("tablename") or request.GET.get("tableName") or "").lower()
        if "transaction" in name:
            records, skipped = adms.parse_transactions(body)
            error = _store_punches(device, records, skipped, body, "")
            if error:
                return error
        elif name == "user":
            store.save_users(device, adms.parse_users_v3(body))
    elif table in ("", "OPTIONS", "REGISTRY"):
        _remember(device, adms.parse_kv(body))
    # Photos, fingerprint/face templates etc. are acknowledged and deliberately discarded.
    return _text("OK")


@adms_endpoint
def getrequest(request, body):
    device, error = _device_for(request)
    if error:
        return error
    pending = list(device.commands.filter(sent_at__isnull=True).order_by("id")[:10])
    if not pending:
        return _text("OK")
    DeviceCommand.objects.filter(pk__in=[c.pk for c in pending]).update(sent_at=timezone.now())
    return _text(adms.format_commands([(c.pk, c.command) for c in pending]))


@adms_endpoint
def devicecmd(request, body):
    device, error = _device_for(request)
    if error:
        return error
    for result in adms.parse_cmd_results(body):
        DeviceCommand.objects.filter(device=device, pk=result["id"]).update(
            result_code=result["ret"], finished_at=timezone.now())
    _remember(device, adms.parse_kv(body))
    return _text("OK")


@adms_endpoint
def registry(request, body):
    """Push 3.x: the device announces itself (keys prefixed with ~ are optional) and expects a RegistryCode."""
    device, error = _device_for(request)
    if error:
        return error
    _remember(device, adms.parse_kv(body))
    info = dict(device.device_info or {})
    code = info.get("RegistryCode") or secrets.token_hex(8)
    if info.get("RegistryCode") != code:
        info["RegistryCode"] = code
        device.device_info = info
        device.save(update_fields=["device_info"])
    return _text(adms.registry_response(code))


@adms_endpoint
def push_config(request, body):
    """Push 3.x: configuration handed to the device after registration."""
    device, error = _device_for(request)
    if error:
        return error
    return _text(adms.push_config_response(secrets.token_hex(8), delay=getattr(settings, "ADMS_DELAY", 30)))


@adms_endpoint
def other(request, body, rest=""):
    """Anything else under /iclock/ (ping, probes...): journal it and say OK."""
    return _text("OK")

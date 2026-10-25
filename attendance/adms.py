"""ZKTeco ADMS / "push" protocol helpers (Django-free, unit-testable).

The device calls the server (HTTP):
  GET  /iclock/cdata?SN=..&options=all   handshake  -> server answers with a "GET OPTION FROM" block
  POST /iclock/cdata?SN=..&table=ATTLOG  punches    -> tab-separated lines, server answers OK
  POST /iclock/cdata?SN=..&table=OPERLOG user/ops   -> "USER PIN=..<TAB>Name=.." lines
  GET  /iclock/getrequest?SN=..          heartbeat + command poll -> OK or "C:<id>:<command>" lines
  POST /iclock/devicecmd?SN=..           command results "ID=1&Return=0&CMD=INFO"
"""
import re
from datetime import datetime

SN_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
DEFAULT_TRANS_FLAG = "TransData AttLog OpLog AttPhoto EnrollUser ChgUser EnrollFP ChgFP UserPic"
_ATT_SPACED = re.compile(r"^(\S+)\s+(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\s*(.*)$")
_FIELD_SPLIT = re.compile(r"\t|\s+(?=[A-Za-z~]\w*=)")


def valid_serial(sn):
    return bool(sn and SN_RE.match(sn))


def _int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_ts(text):
    try:
        return datetime.strptime(str(text).strip().replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _kv(fields):
    out = {}
    for f in fields:
        if "=" in f:
            k, v = f.split("=", 1)
            out[k.strip().lstrip("~").lower()] = v.strip()
    return out


def _parse_att_line(line):
    fields = line.split("\t")
    if len(fields) >= 2 and "=" not in fields[0]:            # PIN <TAB> time <TAB> status <TAB> verify ...
        uid, ts_text, rest = fields[0].strip(), fields[1], [f.strip() for f in fields[2:]]
    elif "=" in fields[0] or "=" in line.split(" ", 1)[0]:     # PIN=1 DateTime=... style
        kv = _kv(_FIELD_SPLIT.split(line))
        uid, ts_text = kv.get("pin", ""), kv.get("datetime") or kv.get("time") or ""
        rest = [kv.get("status", "0"), kv.get("verified") or kv.get("verify") or "0"]
    else:                                                      # space separated fallback
        m = _ATT_SPACED.match(line)
        if not m:
            return None
        uid, ts_text, rest = m.group(1), m.group(2), m.group(3).split()
    ts = _parse_ts(ts_text)
    if not uid or ts is None:
        return None
    return {"user_id": uid[:32], "timestamp": ts,
            "punch_code": _int(rest[0]) if len(rest) > 0 else 0,
            "verify_code": _int(rest[1]) if len(rest) > 1 else 0}


def parse_attlog(body):
    """Returns (records, skipped_line_count). Tolerant: a bad line never rejects the batch."""
    records, skipped = [], 0
    for raw in (body or "").replace("\x00", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        rec = _parse_att_line(line)
        if rec is None:
            skipped += 1
        else:
            records.append(rec)
    return records, skipped


def parse_users(body):
    """Extracts [(pin, name)] from OPERLOG / USERINFO lines such as 'USER PIN=1<TAB>Name=Bob<TAB>Pri=0'."""
    users = []
    for raw in (body or "").replace("\x00", "").splitlines():
        line = raw.strip()
        m = re.match(r"^(USER|USERINFO)\s+(.*)$", line, re.I)
        if m:
            line = m.group(2)
        if "PIN=" not in line.upper():
            continue
        kv = _kv(_FIELD_SPLIT.split(line))
        if kv.get("pin") and "name" in kv:
            users.append((kv["pin"][:32], kv["name"][:100]))
    return users


def parse_kv(body, limit=60):
    """Generic key=value extraction for info/registry payloads (comma, tab, ampersand or newline separated)."""
    out = {}
    for part in re.split(r"[\r\n,&\t]+", body or ""):
        if "=" in part and len(out) < limit:
            k, v = part.split("=", 1)
            k = k.strip().lstrip("~")
            if k and len(k) <= 40:
                out[k] = v.strip()[:200]
    return out


def handshake_response(sn, att_stamp="None", oper_stamp="None", delay=30, error_delay=60,
                       trans_flag=DEFAULT_TRANS_FLAG):
    """Answer to GET /iclock/cdata. ATTLOGStamp tells the device where to resume uploading ('None' = everything)."""
    return "\n".join([
        f"GET OPTION FROM: {sn}",
        f"ATTLOGStamp={att_stamp or 'None'}",
        f"OPERLOGStamp={oper_stamp or 'None'}",
        "ATTPHOTOStamp=None",
        f"ErrorDelay={error_delay}",
        f"Delay={delay}",
        "TransTimes=00:00;14:05",
        "TransInterval=1",
        f"TransFlag={trans_flag}",
        "Realtime=1",
        "Encrypt=None",
    ]) + "\n"


def format_commands(commands):
    """[(id, 'INFO'), ...] -> 'C:1:INFO\\nC:2:...' (empty list -> 'OK')."""
    return "".join(f"C:{cid}:{cmd}\n" for cid, cmd in commands) or "OK"


def parse_cmd_results(body):
    """'ID=1&Return=0&CMD=INFO' (one or several lines) -> [{'id':1,'ret':0,'cmd':'INFO'}]."""
    results = []
    for line in (body or "").splitlines():
        kv = {}
        for part in line.strip().split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k.strip()] = v.strip()
        if "ID" in kv and kv["ID"].lstrip("-").isdigit():
            results.append({"id": int(kv["ID"]), "ret": _int(kv.get("Return"), -999), "cmd": kv.get("CMD", "")})
    return results


# --------------------------------------------------------------------------- upload profiles & push 3.x

TRANS_PROFILES = {
    "standard": DEFAULT_TRANS_FLAG,
    "minimal": "TransData AttLog OpLog EnrollUser ChgUser",   # no fingerprint/face templates or photos
    "numeric": "1111000000",                                    # positional flag used by some older firmware
}


def trans_flag_for(profile, override=""):
    return override or TRANS_PROFILES.get(profile, DEFAULT_TRANS_FLAG)


def decode_body(raw):
    """Devices are not consistent: UTF-8 first, then GB18030 (Chinese firmware), never fails (latin-1)."""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def registry_response(code):
    return f"RegistryCode={code}\n"


def push_config_response(session_id, delay=30, error_delay=60):
    """Push-3.x style configuration (best effort: the field names follow ZKTeco's PUSH 3.x description)."""
    return "\n".join([
        "ServerVersion=3.0.1", "ServerName=ADMS", "PushVersion=3.0.1", f"ErrorDelay={error_delay}",
        f"RequestDelay={delay}", "TransTimes=00:00;14:05", "TransInterval=1", "TransTables=User Transaction",
        "Realtime=1", f"SessionID={session_id}", "TimeoutSec=10",
    ]) + "\n"


_PAIR = re.compile(r"(\w+)=([^,\t]*)")


def _pairs(line):
    return {k.lower(): v.strip() for k, v in _PAIR.findall(line)}


def parse_transactions(body):
    """Push-3.x 'transaction' rows: 'transaction pin=1,time=2026-10-01 08:00:00,verified=1,inoutstate=0'."""
    records, skipped = [], 0
    for raw in (body or "").replace("\x00", "").splitlines():
        if not raw.strip():
            continue
        kv = _pairs(raw)
        ts = _parse_ts(kv.get("time", "") or kv.get("datetime", ""))
        if not kv.get("pin") or ts is None:
            skipped += 1
            continue
        records.append({"user_id": kv["pin"][:32], "timestamp": ts,
                        "punch_code": _int(kv.get("inoutstate", kv.get("status", 0))),
                        "verify_code": _int(kv.get("verified", kv.get("verify", 0)))})
    return records, skipped


def parse_users_v3(body):
    """Push-3.x 'user' rows: 'user pin=1,name=Bob,...'  ->  [(pin, name)]."""
    out = []
    for raw in (body or "").replace("\x00", "").splitlines():
        kv = _pairs(raw)
        if kv.get("pin") and "name" in kv:
            out.append((kv["pin"][:32], kv["name"][:100]))
    return out

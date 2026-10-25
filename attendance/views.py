import datetime as dt
from collections import Counter

from django.db.models import Count
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import adms, services, store
from .forms import DeviceForm, ExportForm, SelectDevicesForm
from .models import Device, DeviceCommand, DeviceRequestLog, Shift

PREVIEW_LIMIT = 500
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORM_TEMPLATE = "attendance/partials/_device_form.html"
# Only harmless, read-only commands are exposed from the UI.
ALLOWED_COMMANDS = {"info": "INFO", "check": "CHECK", "users": "DATA QUERY USERINFO"}


def _devices():
    return Device.objects.annotate(log_count=Count("logs")).order_by("name")


def _render_list(request, extra_html=""):
    html = render_to_string("attendance/partials/_device_list.html", {"devices": _devices()}, request=request)
    return HttpResponse(html + extra_html)


def _add_ctx(form, oob=False):
    return {"form": form, "device": None, "action": reverse("device_add"), "wrapper_id": "add-device", "oob": oob}


def _edit_ctx(form, device):
    return {"form": form, "device": device, "action": reverse("device_edit", args=[device.pk]),
            "wrapper_id": f"device-row-{device.pk}", "oob": False}


def index(request):
    today = dt.date.today()
    ctx = {"devices": _devices(), "start_default": today.replace(day=1).isoformat(),
           "end_default": today.isoformat(), "adms_port": request.get_port()}
    ctx.update(_add_ctx(DeviceForm()))
    return render(request, "attendance/index.html", ctx)


@require_GET
def device_list(request):
    return _render_list(request)


@require_POST
def device_add(request):
    form = DeviceForm(request.POST)
    if form.is_valid():
        form.save()
        blank = render_to_string(FORM_TEMPLATE, _add_ctx(DeviceForm(), oob=True), request=request)
        return _render_list(request, blank)  # list is the main swap; fresh form rides along out-of-band
    resp = render(request, FORM_TEMPLATE, _add_ctx(form))
    resp["HX-Retarget"] = "#add-device"
    resp["HX-Reswap"] = "outerHTML"
    return resp


@require_POST
def device_add_demo(request):
    n = Device.objects.filter(mode="pull", ip_address__istartswith="demo").count() + 1
    Device.objects.create(name=f"Demo device {n}", ip_address="demo", port=4370)
    return _render_list(request)


@require_http_methods(["GET", "POST"])
def device_edit(request, pk):
    device = get_object_or_404(Device, pk=pk)
    if request.method == "POST":
        form = DeviceForm(request.POST, instance=device)
        if form.is_valid():
            form.save()
            return _render_list(request)
        resp = render(request, FORM_TEMPLATE, _edit_ctx(form, device))
        resp["HX-Retarget"] = f"#device-row-{pk}"
        resp["HX-Reswap"] = "outerHTML"
        return resp
    return render(request, FORM_TEMPLATE, _edit_ctx(DeviceForm(instance=device), device))


@require_POST
def device_delete(request, pk):
    get_object_or_404(Device, pk=pk).delete()
    return _render_list(request)


@require_GET
def device_status(request, pk):
    device = get_object_or_404(Device, pk=pk)
    online, latency = services.probe(device)
    return render(request, "attendance/partials/_status.html", {"device": device, "online": online, "latency": latency})


def _info_response(request, device, flash=""):
    info = store.adms_info(device) if device.mode == "adms" else services.device_info(device)
    return render(request, "attendance/partials/_device_info.html", {"device": device, "info": info, "flash": flash})


@require_GET
def device_test(request, pk):
    return _info_response(request, get_object_or_404(Device, pk=pk))


@require_POST
def device_command(request, pk):
    device = get_object_or_404(Device, pk=pk, mode="adms")
    command = ALLOWED_COMMANDS.get(request.POST.get("cmd", ""))
    if not command:
        return HttpResponse("Unknown command", status=400)
    DeviceCommand.objects.create(device=device, command=command)
    return _info_response(request, device, "Queued — the device collects it on its next poll (usually within 30 s).")


@require_POST
def device_resync(request, pk):
    device = get_object_or_404(Device, pk=pk, mode="adms")
    device.att_stamp = device.oper_stamp = "None"
    device.save(update_fields=["att_stamp", "oper_stamp"])
    return _info_response(request, device, "Sync position reset. The device re-uploads all its punches the next "
                                           "time it handshakes (restart it to force that). Duplicates are ignored.")


@require_GET
def adms_log(request):
    return render(request, "attendance/partials/_adms_log.html", {"logs": DeviceRequestLog.objects.all()[:30]})


def _build(cd):
    """Fetch punches (and, if asked, the shift report). Returns (records, summary, shift_rows|None, shift_stats)."""
    start, end = cd["start_date"], cd["end_date"]
    use_shifts = cd["shift_report"] and Shift.objects.exists()
    pad = dt.timedelta(days=1) if use_shifts else dt.timedelta(0)  # night shifts spill over the range edges
    devices = list(cd["devices"])
    records, summary = store.collect(devices, start - pad, end + pad, cd["user_query"],
                                     source=cd["source"], save=cd["save_copy"])
    if not use_shifts:
        return records, summary, None, {}
    rows, stats = store.build_shift_report(records, start, end, cd["user_query"], devices)
    records = [r for r in records if start <= r["timestamp"].date() <= end]
    counts = Counter(r["device"] for r in records)
    for s in summary:
        if not s["error"]:
            s["count"] = counts.get(s["name"], 0)
    return records, summary, rows, stats


def _stats(records):
    return {"users": len({r["user_id"] for r in records}), "days": len({r["timestamp"].date() for r in records})}


@require_POST
def preview(request):
    form = ExportForm(request.POST)
    if not form.is_valid():
        return render(request, "attendance/partials/_results.html", {"form_errors": form.errors.values()})
    cd = form.cleaned_data
    records, summary, shift_rows, shift_stats = _build(cd)
    return render(request, "attendance/partials/_results.html", {
        "records": records[:PREVIEW_LIMIT], "total": len(records), "limit": PREVIEW_LIMIT,
        "summary": summary, "stats": _stats(records), "source": cd["source"],
        "shift_rows": None if shift_rows is None else shift_rows[:PREVIEW_LIMIT],
        "shift_total": len(shift_rows or []), "shift_stats": shift_stats,
    })


@require_POST
def export(request):
    form = ExportForm(request.POST)
    if not form.is_valid():
        return HttpResponse("; ".join(str(e) for errs in form.errors.values() for e in errs), status=400)
    cd = form.cleaned_data
    records, summary, shift_rows, shift_stats = _build(cd)
    if not records and summary and all(s["error"] for s in summary):
        items = "".join(f"<li><b>{escape(s['name'])}</b>: {escape(s['error'])}</li>" for s in summary)
        return HttpResponse(
            f"<h3>Export failed</h3><ul>{items}</ul><p><a href='javascript:history.back()'>Back</a></p>", status=502)
    stem = f"attendance_{cd['start_date']}_{cd['end_date']}"
    if cd["fmt"] == "csv":
        resp = HttpResponse(services.build_csv(records), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{stem}.csv"'
    else:
        buf = services.build_workbook(records, summary, cd["start_date"], cd["end_date"], cd["source"],
                                        shift_rows=shift_rows, shift_stats=shift_stats)
        resp = HttpResponse(buf.getvalue(), content_type=XLSX_MIME)
        resp["Content-Disposition"] = f'attachment; filename="{stem}.xlsx"'
    return resp


@require_POST
def sync(request):
    form = SelectDevicesForm(request.POST)
    if not form.is_valid():
        return render(request, "attendance/partials/_results.html", {"form_errors": form.errors.values()})
    devices = list(form.cleaned_data["devices"])
    pull = [d for d in devices if d.mode == "pull"]
    summary = store.fetch_live(pull, dt.date.min, dt.date.max, "", save=True)[1] if pull else []
    for d in devices:
        if d.mode == "adms":
            seen = f"last seen {d.last_seen:%Y-%m-%d %H:%M}" if d.last_seen else "never seen yet"
            summary.append({"name": d.name, "error": None,
                            "note": f"ADMS device — it pushes punches by itself ({seen}); nothing to pull."})
    return render(request, "attendance/partials/_sync_result.html", {"summary": summary})


@require_GET
def stats(request):
    return render(request, "attendance/partials/_stats.html", {"s": store.dashboard_stats()})


@require_GET
def pending(request):
    return render(request, "attendance/partials/_pending.html", {"pending": store.pending_serials()})


@require_POST
def device_register(request):
    """One-click registration of an unknown ADMS device that has been calling in (and being refused)."""
    serial = request.POST.get("serial", "").strip()
    if not adms.valid_serial(serial):
        return HttpResponse("Invalid serial number", status=400)
    Device.objects.get_or_create(serial_number=serial, defaults={"name": f"ADMS {serial}", "mode": "adms"})
    resp = _render_list(request)
    resp["HX-Trigger"] = "refreshPending"
    return resp


@require_GET
def healthz(request):
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})

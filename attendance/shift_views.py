"""Shift management screens (htmx). Every endpoint returns the whole shifts panel."""
import datetime as dt

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import shifts
from .forms import AssignForm, ShiftForm
from .models import AttendanceLog, DeviceUser, Shift, ShiftAssignment

MAX_NEW_ASSIGNMENTS = 5000


def _panel(request, shift_form=None, assign_form=None, editing=None, flash=""):
    names = dict(DeviceUser.objects.values_list("pin", "name"))
    assignments = list(ShiftAssignment.objects.select_related("shift").order_by("-id")[:100])
    for a in assignments:
        a.display_name = names.get(a.user_id, "")
    return render(request, "attendance/partials/_shifts.html", {
        "shifts": Shift.objects.all(), "shift_form": shift_form or ShiftForm(), "editing": editing,
        "open_form": bool(editing or (shift_form is not None and shift_form.is_bound)),
        "assign_form": assign_form or AssignForm(initial={"start_date": dt.date.today()}),
        "assignments": assignments, "flash": flash,
    })


@require_GET
def shifts_panel(request):
    return _panel(request)


@require_POST
def shift_seed(request):
    """One click: create an example Day and Night shift so the rest can be tried immediately."""
    made = []
    if not Shift.objects.filter(name="Day").exists():
        Shift.objects.create(name="Day", start_time=dt.time(8, 0), end_time=dt.time(17, 0), work_days="0,1,2,3,4",
                             is_default=not Shift.objects.filter(is_default=True).exists())
        made.append("Day 08:00–17:00")
    if not Shift.objects.filter(name="Night").exists():
        Shift.objects.create(name="Night", start_time=dt.time(20, 0), end_time=dt.time(6, 0), work_days="0,1,2,3,4,5")
        made.append("Night 20:00–06:00")
    return _panel(request, flash=("Created " + " and ".join(made) + ".") if made else "Day and Night already exist.")


@require_POST
def shift_add(request):
    form = ShiftForm(request.POST)
    if form.is_valid():
        form.save()
        return _panel(request, flash="Shift saved.")
    return _panel(request, shift_form=form)


@require_http_methods(["GET", "POST"])
def shift_edit(request, pk):
    shift = get_object_or_404(Shift, pk=pk)
    if request.method == "POST":
        form = ShiftForm(request.POST, instance=shift)
        if form.is_valid():
            form.save()
            return _panel(request, flash="Shift updated.")
        return _panel(request, shift_form=form, editing=shift)
    return _panel(request, shift_form=ShiftForm(instance=shift), editing=shift)


@require_POST
def shift_delete(request, pk):
    get_object_or_404(Shift, pk=pk).delete()
    return _panel(request, flash="Shift and its assignments deleted.")


@require_POST
def assign_add(request):
    form = AssignForm(request.POST)
    if not form.is_valid():
        return _panel(request, assign_form=form)
    cd = form.cleaned_data
    users = cd["user_ids"]
    if "*" in users:
        users = sorted(set(AttendanceLog.objects.values_list("user_id", flat=True).distinct())
                       | set(DeviceUser.objects.values_list("pin", flat=True)), key=shifts.uid_key)
        if not users:
            form.add_error("user_ids", "No employees known yet — list their IDs instead.")
            return _panel(request, assign_form=form)
    if cd["rotate_with"]:
        blocks = [(s, e, cd["shift"] if i % 2 == 0 else cd["rotate_with"])
                  for s, e, i in shifts.rotation_blocks(cd["start_date"], cd["end_date"], cd["rotate_weeks"] or 1)]
    else:
        blocks = [(cd["start_date"], cd["end_date"], cd["shift"])]
    if len(users) * len(blocks) > MAX_NEW_ASSIGNMENTS:
        form.add_error(None, "That would create too many assignments; use a shorter date range.")
        return _panel(request, assign_form=form)
    ShiftAssignment.objects.bulk_create([
        ShiftAssignment(user_id=u, shift=sh, start_date=s, end_date=e) for u in users for s, e, sh in blocks])
    return _panel(request, flash=f"Assigned {len(users)} employee(s), {len(blocks)} period(s) each.")


@require_POST
def assign_delete(request, pk):
    get_object_or_404(ShiftAssignment, pk=pk).delete()
    return _panel(request, flash="Assignment removed.")

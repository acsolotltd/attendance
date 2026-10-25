import re

from django import forms

from . import adms
from .models import Device, Shift

INPUT = "input"


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["name", "mode", "serial_number", "ip_address", "port", "comm_key", "timeout", "protocol",
                  "encoding", "trans_profile", "punch_state_unused"]
        labels = {
            "name": "Name",
            "mode": "Connection mode",
            "serial_number": "Serial number (SN)",
            "ip_address": "Public IP / hostname (or “demo”)",
            "port": "Port",
            "comm_key": "Comm Key (0 = none)",
            "timeout": "Timeout (seconds)",
            "protocol": "Protocol",
            "encoding": "Name encoding",
            "trans_profile": "Data the device uploads",
            "punch_state_unused": "Device doesn't record in/out state (show “Punch”)",
        }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", False)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "punch_state_unused":
                field.widget.attrs.setdefault("class", INPUT)
        for name in ("protocol", "encoding", "trans_profile"):  # optional: the model defaults apply when omitted
            self.fields[name].required = False

    def clean_ip_address(self):
        value = re.sub(r"^[a-z]+://", "", self.cleaned_data["ip_address"].strip(), flags=re.I).rstrip("/")
        if ":" in value or "/" in value or " " in value:
            raise forms.ValidationError("Enter only the IP or hostname — put the port in the Port field.")
        return value

    def clean_serial_number(self):
        return self.cleaned_data["serial_number"].strip()

    def clean_port(self):
        port = self.cleaned_data["port"]
        if not 1 <= port <= 65535:
            raise forms.ValidationError("Port must be between 1 and 65535.")
        return port

    def clean_timeout(self):
        timeout = self.cleaned_data["timeout"]
        if not 3 <= timeout <= 180:
            raise forms.ValidationError("Timeout must be between 3 and 180 seconds.")
        return timeout

    def clean(self):
        data = super().clean()
        mode = data.get("mode")
        if mode == "adms":
            sn = data.get("serial_number", "")
            if not sn:
                self.add_error("serial_number", "Enter the device serial number (Menu > System Info), "
                                                "or leave this device to register itself when it first connects.")
            elif not adms.valid_serial(sn):
                self.add_error("serial_number", "Use 3–64 letters, digits, dots, dashes or underscores.")
        elif mode == "pull":
            data["serial_number"] = ""
            if not data.get("ip_address") and "ip_address" not in self.errors:
                self.add_error("ip_address", "Required for pull mode.")
        return data


class SelectDevicesForm(forms.Form):
    devices = forms.ModelMultipleChoiceField(
        queryset=Device.objects.all(),
        error_messages={"required": "Select at least one device."},
    )


class ExportForm(SelectDevicesForm):
    start_date = forms.DateField()
    end_date = forms.DateField()
    user_query = forms.CharField(required=False)
    source = forms.ChoiceField(choices=[("live", "Live"), ("db", "Local database")], required=False)
    fmt = forms.ChoiceField(choices=[("xlsx", "Excel"), ("csv", "CSV")], required=False)
    save_copy = forms.BooleanField(required=False)
    shift_report = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        data["source"] = data.get("source") or "live"
        data["fmt"] = data.get("fmt") or "xlsx"
        s, e = data.get("start_date"), data.get("end_date")
        if s and e and e < s:
            raise forms.ValidationError("End date must be on or after the start date.")
        return data


DAYS = [("0", "Mon"), ("1", "Tue"), ("2", "Wed"), ("3", "Thu"), ("4", "Fri"), ("5", "Sat"), ("6", "Sun")]


class ShiftForm(forms.ModelForm):
    work_days = forms.MultipleChoiceField(
        choices=DAYS, widget=forms.CheckboxSelectMultiple, label="Work days",
        error_messages={"required": "Pick at least one work day."})

    class Meta:
        model = Shift
        fields = ["name", "start_time", "end_time", "work_days", "grace_minutes", "overtime_after_minutes",
                  "window_before_minutes", "window_after_minutes", "is_default"]
        widgets = {"start_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
                   "end_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"})}
        labels = {"name": "Name", "start_time": "Starts", "end_time": "Ends (earlier than start = next day)",
                  "grace_minutes": "Late/early grace (min)", "overtime_after_minutes": "Overtime counts after (min)",
                  "window_before_minutes": "Accept punches this early (min)",
                  "window_after_minutes": "...and this late after the end (min)",
                  "is_default": "Default shift (for people with no assignment)"}

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", False)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ("work_days", "is_default"):
                field.widget.attrs.setdefault("class", INPUT)
        if not self.is_bound:
            self.initial["work_days"] = (self.instance.work_days.split(",") if self.instance.pk
                                         else ["0", "1", "2", "3", "4"])

    def clean_work_days(self):
        return ",".join(sorted(self.cleaned_data["work_days"]))

    def clean(self):
        data = super().clean()
        if data.get("start_time") is not None and data.get("start_time") == data.get("end_time"):
            self.add_error("end_time", "Start and end can't be the same time.")
        return data

    def save(self, commit=True):
        shift = super().save(commit)
        if commit and shift.is_default:
            Shift.objects.exclude(pk=shift.pk).update(is_default=False)
        return shift


class AssignForm(forms.Form):
    shift = forms.ModelChoiceField(queryset=Shift.objects.all(), empty_label=None)
    user_ids = forms.CharField(label="Employee IDs (PINs)")
    start_date = forms.DateField(widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    rotate_with = forms.ModelChoiceField(queryset=Shift.objects.all(), required=False,
                                         empty_label="— no rotation —")
    rotate_weeks = forms.IntegerField(required=False, min_value=1, max_value=12, initial=1)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", False)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT)

    def clean_user_ids(self):
        tokens = [t for t in re.split(r"[,;\s]+", self.cleaned_data["user_ids"]) if t]
        if not tokens:
            raise forms.ValidationError("Enter at least one employee ID, or * for everyone known.")
        for t in tokens:
            if t != "*" and not re.match(r"^[A-Za-z0-9._-]{1,32}$", t):
                raise forms.ValidationError(f"“{t}” isn't a valid ID.")
        return tokens

    def clean(self):
        data = super().clean()
        start, end, rot = data.get("start_date"), data.get("end_date"), data.get("rotate_with")
        if start and end and end < start:
            self.add_error("end_date", "End date must be on or after the start date.")
        if rot:
            if rot == data.get("shift"):
                self.add_error("rotate_with", "Pick a different shift to rotate with.")
            if not end:
                self.add_error("end_date", "Rotation needs an end date.")
        return data

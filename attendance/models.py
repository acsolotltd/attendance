from django.db import models


class Device(models.Model):
    MODES = [
        ("pull", "Pull — this server connects to the device (TCP 4370)"),
        ("adms", "ADMS / push — the device connects to this server"),
    ]
    PROTOCOLS = [("tcp", "TCP (default)"), ("udp", "UDP")]
    ENCODINGS = [("UTF-8", "UTF-8 (default)"), ("GBK", "GBK (Chinese firmware)"), ("latin-1", "Latin-1")]
    PROFILES = [("standard", "Standard (recommended)"), ("minimal", "Minimal: no templates/photos"),
                ("numeric", "Legacy numeric flag")]

    name = models.CharField(max_length=100)
    mode = models.CharField(max_length=4, choices=MODES, default="pull")
    serial_number = models.CharField(max_length=64, blank=True, default="")  # ADMS identifies devices by SN
    ip_address = models.CharField(max_length=255, blank=True, default="")  # pull mode: public IP, hostname or "demo"
    port = models.PositiveIntegerField(default=4370)
    comm_key = models.PositiveIntegerField(default=0)
    timeout = models.PositiveSmallIntegerField(default=15)
    protocol = models.CharField(max_length=3, choices=PROTOCOLS, default="tcp")
    encoding = models.CharField(max_length=12, choices=ENCODINGS, default="UTF-8")  # pull: how names are encoded
    trans_profile = models.CharField(max_length=10, choices=PROFILES, default="standard")  # ADMS: what it uploads
    punch_state_unused = models.BooleanField(default=False)  # some firmware always reports one fixed state
    last_sync_at = models.DateTimeField(null=True, blank=True)
    # ADMS state
    last_seen = models.DateTimeField(null=True, blank=True)
    last_ip = models.CharField(max_length=45, blank=True, default="")
    att_stamp = models.CharField(max_length=32, default="None")    # where the device resumes uploading punches
    oper_stamp = models.CharField(max_length=32, default="None")
    device_info = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["serial_number"], condition=~models.Q(serial_number=""), name="uniq_device_serial",
                violation_error_message="That serial number is already registered.",
            )
        ]

    def __str__(self):
        if self.mode == "adms":
            return f"{self.name} (ADMS {self.serial_number})"
        return f"{self.name} ({self.ip_address}:{self.port})"

    @property
    def is_demo(self):
        return self.mode == "pull" and str(self.ip_address).strip().lower().startswith("demo")


class AttendanceLog(models.Model):
    """Local copy of punches (pulled or pushed). Safe against the device overwriting old logs."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="logs")
    user_id = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=100, blank=True, default="")
    timestamp = models.DateTimeField(db_index=True)
    punch = models.SmallIntegerField(default=0)
    verify = models.SmallIntegerField(default=0)

    class Meta:
        ordering = ["timestamp", "user_id"]
        unique_together = [("device", "user_id", "timestamp")]
        indexes = [models.Index(fields=["device", "timestamp"], name="log_device_ts_idx")]

    def __str__(self):
        return f"{self.user_id} @ {self.timestamp}"


class DeviceUser(models.Model):
    """Names learned from the device (ADMS OPERLOG/USERINFO) so punches show names, not just PINs."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="users")
    pin = models.CharField(max_length=32)
    name = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        unique_together = [("device", "pin")]


class DeviceCommand(models.Model):
    """Commands queued for an ADMS device; delivered when it next polls /iclock/getrequest."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="commands")
    command = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result_code = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


class DeviceRequestLog(models.Model):
    """Rolling log of the most recent /iclock/* requests, for troubleshooting what a device really sends."""

    created_at = models.DateTimeField(auto_now_add=True)
    serial = models.CharField(max_length=64, blank=True, default="")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=500)
    body_preview = models.TextField(blank=True, default="")
    response_preview = models.CharField(max_length=300, blank=True, default="")
    status = models.PositiveSmallIntegerField(default=200)
    remote_ip = models.CharField(max_length=45, blank=True, default="")

    class Meta:
        ordering = ["-id"]


class Shift(models.Model):
    """A work shift. If end_time <= start_time the shift runs past midnight (night shift)."""

    name = models.CharField(max_length=60, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    work_days = models.CharField(max_length=20, default="0,1,2,3,4")  # Mon=0 .. Sun=6
    grace_minutes = models.PositiveSmallIntegerField(default=10)
    overtime_after_minutes = models.PositiveSmallIntegerField(default=30)
    window_before_minutes = models.PositiveSmallIntegerField(default=120)  # punches this early still belong to it
    window_after_minutes = models.PositiveSmallIntegerField(default=180)   # ...and this late after the end
    is_default = models.BooleanField(default=False)  # used for people with no assignment

    class Meta:
        ordering = ["start_time", "name"]

    def __str__(self):
        return f"{self.name} {self.start_time:%H:%M}–{self.end_time:%H:%M}"

    @property
    def crosses_midnight(self):
        return self.end_time <= self.start_time

    @property
    def days_label(self):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return ", ".join(names[int(d)] for d in self.work_days.split(",") if d != "")

    def as_dict(self):
        return {"id": self.pk, "name": self.name, "start": self.start_time, "end": self.end_time,
                "days": {int(d) for d in self.work_days.split(",") if d != ""}, "grace": self.grace_minutes,
                "ot_after": self.overtime_after_minutes, "before": self.window_before_minutes,
                "after": self.window_after_minutes, "is_default": self.is_default}


class ShiftAssignment(models.Model):
    """Who works which shift, and when. If several rows cover a day, the newest one wins."""

    user_id = models.CharField(max_length=32, db_index=True)  # the PIN on the device
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name="assignments")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

from django.contrib import admin

from .models import AttendanceLog, Device, DeviceCommand, DeviceRequestLog, DeviceUser, Shift, ShiftAssignment


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "mode", "serial_number", "ip_address", "port", "last_seen", "last_sync_at")


@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "device", "user_id", "name", "punch", "verify")
    list_filter = ("device",)
    search_fields = ("user_id", "name")


admin.site.register(DeviceUser)
admin.site.register(DeviceCommand)
admin.site.register(DeviceRequestLog)
admin.site.register(Shift)
admin.site.register(ShiftAssignment)

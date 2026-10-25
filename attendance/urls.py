from django.urls import path

from . import adms_views, shift_views, views

urlpatterns = [
    # --- UI (login required) ---
    path("", views.index, name="index"),
    path("devices/", views.device_list, name="device_list"),
    path("devices/add/", views.device_add, name="device_add"),
    path("devices/add-demo/", views.device_add_demo, name="device_add_demo"),
    path("devices/<int:pk>/edit/", views.device_edit, name="device_edit"),
    path("devices/<int:pk>/delete/", views.device_delete, name="device_delete"),
    path("devices/<int:pk>/status/", views.device_status, name="device_status"),
    path("devices/<int:pk>/test/", views.device_test, name="device_test"),
    path("devices/<int:pk>/command/", views.device_command, name="device_command"),
    path("devices/<int:pk>/resync/", views.device_resync, name="device_resync"),
    path("activity/", views.adms_log, name="adms_log"),
    path("stats/", views.stats, name="stats"),
    path("pending/", views.pending, name="pending"),
    path("devices/register/", views.device_register, name="device_register"),
    path("healthz", views.healthz, name="healthz"),
    path("shifts/", shift_views.shifts_panel, name="shifts_panel"),
    path("shifts/seed/", shift_views.shift_seed, name="shift_seed"),
    path("shifts/add/", shift_views.shift_add, name="shift_add"),
    path("shifts/<int:pk>/edit/", shift_views.shift_edit, name="shift_edit"),
    path("shifts/<int:pk>/delete/", shift_views.shift_delete, name="shift_delete"),
    path("shifts/assign/", shift_views.assign_add, name="assign_add"),
    path("shifts/assign/<int:pk>/delete/", shift_views.assign_delete, name="assign_delete"),
    path("preview/", views.preview, name="preview"),
    path("export/", views.export, name="export"),
    path("sync/", views.sync, name="sync"),
    # --- ADMS endpoints (called by the devices, no login) ---
    path("iclock/cdata", adms_views.cdata, name="iclock_cdata"),
    path("iclock/getrequest", adms_views.getrequest, name="iclock_getrequest"),
    path("iclock/devicecmd", adms_views.devicecmd, name="iclock_devicecmd"),
    path("iclock/registry", adms_views.registry, name="iclock_registry"),
    path("iclock/push", adms_views.push_config, name="iclock_push"),
    path("iclock/<path:rest>", adms_views.other, name="iclock_other"),
]

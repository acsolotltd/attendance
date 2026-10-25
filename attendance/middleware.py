from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    """Everything needs a login except the device endpoints (/iclock/), login pages and the admin."""

    EXEMPT = ("/iclock/", "/accounts/", "/admin/", "/static/", "/healthz")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(self.EXEMPT):
            login_url = f"{settings.LOGIN_URL}?next={quote(request.get_full_path())}"
            if request.headers.get("HX-Request"):
                resp = HttpResponse(status=401)  # htmx: send the whole page to the login screen
                resp["HX-Redirect"] = login_url
                return resp
            return redirect(login_url)
        return self.get_response(request)

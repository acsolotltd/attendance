from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.http import HttpResponse

from .adms_views import client_ip

MAX_FAILURES = 8
WINDOW_SECONDS = 15 * 60


class ThrottledLoginView(LoginView):
    """Login with a small brute-force brake: too many failures from one address pause logins for 15 minutes."""

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs.setdefault("class", "input")
        return form

    def _key(self):
        return f"login-fail:{client_ip(self.request)}"

    def dispatch(self, request, *args, **kwargs):
        self.request = request
        if request.method == "POST" and cache.get(self._key(), 0) >= MAX_FAILURES:
            return HttpResponse("Too many failed sign-in attempts. Try again in 15 minutes.", status=429,
                                content_type="text/plain")
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._key()
        cache.add(key, 0, WINDOW_SECONDS)
        try:
            cache.incr(key)
        except ValueError:
            pass
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)

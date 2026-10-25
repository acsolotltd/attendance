from functools import lru_cache


@lru_cache(maxsize=1)
def _built():
    from django.contrib.staticfiles import finders
    return bool(finders.find("attendance/tailwind.css")) and bool(finders.find("attendance/htmx.min.js"))


def assets(request):
    """True once `npm run build` produced local Tailwind + htmx; otherwise templates fall back to the CDNs."""
    return {"assets_built": _built()}

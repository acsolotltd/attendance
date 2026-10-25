# --- 1) build Tailwind CSS + vendor htmx (no CDNs in production) ---
FROM node:20-alpine AS assets
WORKDIR /src
COPY package.json tailwind.config.js ./
COPY static_src ./static_src
COPY attendance ./attendance
RUN npm install --no-audit --no-fund && npm run build

# --- 2) app ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=assets /src/attendance/static/attendance/tailwind.css /src/attendance/static/attendance/htmx.min.js attendance/static/attendance/
RUN DJANGO_SECRET_KEY=build-only DJANGO_ALLOWED_HOSTS=build python manage.py collectstatic --noinput \
 && useradd --system --uid 10001 app && mkdir -p /data/cache && chown -R app /data
USER app
ENV DJANGO_DB_PATH=/data/db.sqlite3 DJANGO_CACHE_DIR=/data/cache
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request as u;h=os.environ['DJANGO_ALLOWED_HOSTS'].split(',')[0];u.urlopen(u.Request('http://127.0.0.1:8000/healthz',headers={'Host':h}),timeout=4)" || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]

# Grok Register Web — server deployment image.
#
# The app drives real browsers, so the image ships Chromium (browser
# registration backend) plus Xvfb, because headful Chrome inside a virtual
# display is the verified baseline (see scripts/run_with_xvfb.sh).
# Set WITH_SOLVER=0 at build time to skip the ~250MB Camoufox solver stack.
FROM python:3.12-slim-bookworm

ARG WITH_SOLVER=1

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app \
    DISPLAY=:99 \
    GROK_REGISTER_BROWSER_PATH=/usr/bin/chromium \
    GROK_REGISTER_BROWSER_HEADLESS=false

# chromium + xvfb/xauth drive the browser backend; the lib* set covers both
# Chromium and the Camoufox (Firefox) solver runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      xvfb \
      xauth \
      tzdata \
      ca-certificates \
      fonts-liberation \
      fonts-noto-core \
      fonts-noto-cjk \
      fonts-noto-color-emoji \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libatspi2.0-0 \
      libcairo2 \
      libcups2 \
      libdbus-glib-1-2 \
      libdrm2 \
      libgbm1 \
      libgtk-3-0 \
      libnspr4 \
      libnss3 \
      libpango-1.0-0 \
      libx11-xcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxfixes3 \
      libxkbcommon0 \
      libxrandr2 \
      libxt6 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --home-dir /home/app --shell /bin/bash app

WORKDIR /app

# Dependency layer first so source edits do not invalidate the pip cache.
COPY requirements.txt requirements-solver.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_SOLVER" = "1" ]; then pip install -r requirements-solver.txt; fi

COPY . .
RUN chmod +x docker/entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

# Pre-download the Camoufox browser (~100MB) so the first solver start does not
# stall on a runtime download. Best-effort: solver_manager retries at runtime.
RUN if [ "$WITH_SOLVER" = "1" ]; then python -m camoufox fetch || \
      echo 'WARNING: camoufox fetch failed at build time; will retry on first solver start'; fi

EXPOSE 5000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('GROK_REGISTER_PORT','5000')+'/', timeout=4)" || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]

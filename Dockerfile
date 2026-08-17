# Bakes in Python + all pip dependencies + the Tesseract OCR system binary,
# so there is no separate OCR install step for whoever runs this image --
# the one real external dependency this project has (see README "OCR setup").
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies copied and installed before the rest of the source so this
# layer stays cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gst_agent/ gst_agent/

# tests/ + pyproject.toml so the built image can run its own test suite
# (`docker run --rm --entrypoint pytest gst-law-docs-agent -q`, see README
# "Testing guide") -- pytest itself is already installed via
# requirements.txt, but without these two the container has no tests to
# discover and silently reports "no tests ran" instead of actually
# validating anything.
COPY tests/ tests/
COPY pyproject.toml .

# Downloaded PDFs, the SQLite state DB, and logs must survive container
# restarts/recreation -- mount a host directory here, e.g.:
#   docker run -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.main --once
VOLUME ["/app/data"]

# gst_agent/web.py binds to 127.0.0.1 by default (safe for native/local
# use, since the UI has no authentication). Inside a container that must be
# widened, or `-p` port publishing can never reach it -- Docker forwards to
# the container's external interface, not its loopback.
ENV WEB_UI_HOST=0.0.0.0
EXPOSE 5000

# ENTRYPOINT + CMD are split so either module can be run without rebuilding:
#   docker run -v "$(pwd)/data:/app/data" gst-law-docs-agent                       (default: one pass, --once)
#   docker run -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.main --stats
#   docker run -p 5000:5000 -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.web
ENTRYPOINT ["python", "-m"]
CMD ["gst_agent.main", "--once"]

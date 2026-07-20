FROM debian:trixie-backports

ENV DEBIAN_FRONTEND=noninteractive \
	PATH="/opt/venv/bin:$PATH" \
	PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

RUN apt-get update \
	&& apt-get install --yes --no-install-recommends python3 python3-venv ca-certificates \
	&& python3 -m venv /opt/venv \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt \
	&& python -m playwright install --with-deps firefox \
	&& rm -rf /var/lib/apt/lists/*

COPY fusi ./fusi

RUN useradd --create-home --shell /usr/sbin/nologin fusi \
	&& chown -R fusi:fusi /app

USER fusi

ENTRYPOINT ["python", "-m", "fusi"]

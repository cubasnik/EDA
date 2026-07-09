# EDA (Enhanced Dynamic Activation) - virtual network element image
FROM python:3.11-slim

LABEL org.opencontainers.image.title="eda-vne" \
      org.opencontainers.image.description="EDA Enhanced Dynamic Activation virtual network element" \
      org.opencontainers.image.version="1.1.0"

RUN useradd --create-home --shell /bin/bash eda

WORKDIR /opt/eda

COPY pyproject.toml requirements.txt ./
COPY eda ./eda

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Persistent state (SQLite DB) lives under /var/lib/eda so it can be
# mounted as a Cinder volume for a "real" VNE deployment.
RUN mkdir -p /var/lib/eda && chown -R eda:eda /var/lib/eda

ENV EDA_DB_PATH=/var/lib/eda/eda.db \
    EDA_API_HOST=0.0.0.0 \
    EDA_API_PORT=8080 \
    EDA_NE_NAME=eda-vne-01 \
    EDA_NE_TYPE=virtual-network-element

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER eda
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('EDA_API_PORT','8080')+'/health', timeout=3)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

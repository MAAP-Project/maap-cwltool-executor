ARG BASE_IMAGE_NAME=python:3.12-slim
FROM ${BASE_IMAGE_NAME}

USER root

# Install minimal OS deps + Docker CLI (static)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://download.docker.com/linux/static/stable/$(uname -m)/docker-27.0.3.tgz \
      | tar -xz --strip-components=1 -C /usr/local/bin docker/docker

WORKDIR /app

# Install Python deps first (better caching)
RUN pip install --no-cache-dir \
    cwltool==3.1.20250110105449 \
    cwl_utils==0.35 \
    PyYAML \
    awscli \
    pystac==1.15.2 \
    maap-py==5.1.0 \
    requests \
    "urllib3>=2"

# Copy only what you need
COPY docker_stats/docker-stats-on-exit-shim /docker-stats-on-exit-shim
COPY docker_stats/entrypoint-pge-with-stats.sh /entrypoint-pge-with-stats.sh
COPY --chmod=775 . /app/

CMD ["/bin/bash"]

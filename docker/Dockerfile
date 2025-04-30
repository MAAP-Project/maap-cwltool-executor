ARG BASE_IMAGE_NAME=python:3.12
FROM ${BASE_IMAGE_NAME}

# Switch user to root explicitly
USER root
# Install dependencies and Docker CLI
RUN apt-get update && \
    apt-get install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir /app

WORKDIR /app

COPY --chmod=775 . /app/

RUN pip install cwltool==3.1.20250110105449 PyYAML awscli cwl_utils==0.35 pystac maap-py  requests

# copy over docker stats shim utility
COPY docker_stats/docker-stats-on-exit-shim /docker-stats-on-exit-shim

# copy over bash scripts for entrypoints
COPY docker_stats/entrypoint-pge-with-stats.sh /entrypoint-pge-with-stats.sh

CMD ["/bin/bash"]

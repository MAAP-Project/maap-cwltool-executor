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

RUN mkdir /app && pip install cwltool==3.1.20250110105449 PyYAML awscli

COPY dps_wrapper.py /app/dps_wrapper.py
COPY dps_wrapper.sh /app/dps_wrapper.sh
COPY create_inputs.py /app/create_inputs.py
COPY pre_dps_wrapper.py /app/pre_dps_wrapper.py
COPY get_param.py /app/get_param.py
COPY get_username.py /app/get_username.py
COPY aws-config /app/aws-config
COPY get_maap_pgt_token.py /app/get_maap_pgt_token.py

# copy over docker stats shim utility
COPY docker_stats/docker-stats-on-exit-shim /docker-stats-on-exit-shim

# copy over bash scripts for entrypoints
COPY docker_stats/entrypoint-pge-with-stats.sh /entrypoint-pge-with-stats.sh

CMD ["/bin/bash"]

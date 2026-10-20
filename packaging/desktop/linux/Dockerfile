ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 python3-venv python3-dev libpython3.10 \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
    gir1.2-ayatanaappindicator3-0.1 binutils rpm xvfb xauth dbus-x11 \
    desktop-file-utils fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work

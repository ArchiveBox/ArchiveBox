# This is the Dockerfile for ArchiveBox, it bundles the following main dependencies:
#     python3.11, pip, pipx, uv, python3-ldap
#     curl, wget, git, dig, ping, tree, nano
#     node, npm, single-file, readability-extractor, postlight-parser
#     ArchiveBox, yt-dlp, playwright, chromium
# Usage:
#     git clone https://github.com/ArchiveBox/ArchiveBox && cd ArchiveBox
#     docker build . -t archivebox
#     docker run -v "$PWD/data":/data archivebox init
#     docker run -v "$PWD/data":/data archivebox add 'https://example.com'
#     docker run -v "$PWD/data":/data -it archivebox manage createsuperuser
#     docker run -v "$PWD/data":/data -p 8000:8000 archivebox server
# Multi-arch build:
#     docker buildx create --use
#     docker buildx build . --platform=linux/amd64,linux/arm64--push -t archivebox/archivebox:dev -t archivebox/archivebox:sha-abc123
# Read more here: https://github.com/ArchiveBox/ArchiveBox#archivebox-development


#########################################################################################

### Example: Using ArchiveBox in your own project's Dockerfile ########

# FROM python:3.12-slim
# WORKDIR /data
# RUN pip install archivebox>=0.8.5rc51   # use latest release here
# RUN archivebox install
# RUN useradd -ms /bin/bash archivebox && chown -R archivebox /data

#########################################################################################

FROM ubuntu:24.04

LABEL name="archivebox" \
    maintainer="Nick Sweeting <dockerfile@archivebox.io>" \
    description="All-in-one self-hosted internet archiving solution" \
    homepage="https://github.com/ArchiveBox/ArchiveBox" \
    documentation="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker" \
    org.opencontainers.image.title="ArchiveBox" \
    org.opencontainers.image.vendor="ArchiveBox" \
    org.opencontainers.image.description="All-in-one self-hosted internet archiving solution" \
    org.opencontainers.image.source="https://github.com/ArchiveBox/ArchiveBox" \
    com.docker.image.source.entrypoint="Dockerfile" \
    # TODO: release ArchiveBox as a Docker Desktop extension (requires these labels):
    # https://docs.docker.com/desktop/extensions-sdk/architecture/metadata/
    com.docker.desktop.extension.api.version=">= 1.4.7" \
    com.docker.desktop.extension.icon="https://archivebox.io/icon.png" \
    com.docker.extension.publisher-url="https://archivebox.io" \
    com.docker.extension.screenshots='[{"alt": "Screenshot of Admin UI", "url": "https://github.com/ArchiveBox/ArchiveBox/assets/511499/e8e0b6f8-8fdf-4b7f-8124-c10d8699bdb2"}]' \
    com.docker.extension.detailed-description='See here for detailed documentation: https://wiki.archivebox.io' \
    com.docker.extension.changelog='See here for release notes: https://github.com/ArchiveBox/ArchiveBox/releases' \
    com.docker.extension.categories='database,utility-tools'

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
######### Environment Variables #################################

# Global built-time and runtime environment constants + default pkg manager config
ENV TZ=UTC \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    npm_config_loglevel=error

# Language Version config
ENV PYTHON_VERSION=3.12 \
    NODE_VERSION=22

# Non-root User config
ENV ARCHIVEBOX_USER="archivebox" \
    DEFAULT_PUID=911 \
    DEFAULT_PGID=911 \
    IN_DOCKER=True

# ArchiveBox Source Code + Lib + Data paths
ENV CODE_DIR=/app \
    DATA_DIR=/data \
    PLAYWRIGHT_BROWSERS_PATH=/browsers
    # GLOBAL_VENV=/venv \
    # TODO: add TMP_DIR and LIB_DIR?

# Bash SHELL config
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
SHELL ["/bin/bash", "-o", "pipefail", "-o", "errexit", "-o", "errtrace", "-o", "nounset", "-c"] 

######### System Environment ####################################

# Detect ArchiveBox version number by reading pyproject.toml (also serves to invalidate the entire build cache whenever pyproject.toml changes)
WORKDIR "$CODE_DIR"

# Force apt to leave downloaded binaries in /var/cache/apt (massively speeds up back-to-back Docker builds)
RUN echo 'Binary::apt::APT::Keep-Downloaded-Packages "1";' > /etc/apt/apt.conf.d/99keep-cache \
    && echo 'APT::Install-Recommends "0";' > /etc/apt/apt.conf.d/99no-intall-recommends \
    && echo 'APT::Install-Suggests "0";' > /etc/apt/apt.conf.d/99no-intall-suggests \
    && rm -f /etc/apt/apt.conf.d/docker-clean

# Print debug info about build and save it to disk, for human eyes only, not used by anything else
RUN (echo "[i] Docker build for ArchiveBox starting..." \
    && echo "PLATFORM=${TARGETPLATFORM} ARCH=$(uname -m) ($(uname -s) ${TARGETARCH} ${TARGETVARIANT})" \
    && echo "BUILD_START_TIME=$(date +"%Y-%m-%d %H:%M:%S %s") TZ=${TZ} LANG=${LANG}" \
    && echo \
    && echo "PYTHON=${PYTHON_VERSION} NODE=${NODE_VERSION} PATH=${PATH}" \
    && echo "CODE_DIR=${CODE_DIR} DATA_DIR=${DATA_DIR}" \
    && echo \
    && uname -a \
    && cat /etc/os-release | head -n7 \
    && which bash && bash --version | head -n1 \
    && which dpkg && dpkg --version | head -n1 \
    && echo -e '\n\n' && env && echo -e '\n\n' \
    ) | tee -a /VERSION.txt

# Create non-privileged user for archivebox and chrome
RUN echo "[*] Setting up $ARCHIVEBOX_USER user uid=${DEFAULT_PUID}..." \
    && groupadd --system $ARCHIVEBOX_USER \
    && useradd --system --create-home --gid $ARCHIVEBOX_USER --groups audio,video $ARCHIVEBOX_USER \
    && usermod -u "$DEFAULT_PUID" "$ARCHIVEBOX_USER" \
    && groupmod -g "$DEFAULT_PGID" "$ARCHIVEBOX_USER" \
    && echo -e "\nARCHIVEBOX_USER=$ARCHIVEBOX_USER PUID=$(id -u $ARCHIVEBOX_USER) PGID=$(id -g $ARCHIVEBOX_USER)\n\n" \
    | tee -a /VERSION.txt
    # DEFAULT_PUID and DEFAULT_PID are overriden by PUID and PGID in /bin/docker_entrypoint.sh at runtime
    # https://docs.linuxserver.io/general/understanding-puid-and-pgid

# Install system apt dependencies (adding backports to access more recent apt updates)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    echo "[+] APT Installing base system dependencies for $TARGETPLATFORM..." \
    && mkdir -p /etc/apt/keyrings \
    && apt-get update -qq \
    && apt-get install -qq -y \
        # 1. packaging dependencies
        apt-transport-https ca-certificates apt-utils gnupg2 curl wget \
        # 2. docker and init system dependencies
        zlib1g-dev dumb-init gosu cron unzip grep dnsutils \
        # 3. frivolous CLI helpers to make debugging failed archiving easier
        tree nano iputils-ping \
        # nano iputils-ping dnsutils htop procps jq yq
    && rm -rf /var/lib/apt/lists/*

# Install apt binary dependencies for exractors
# COPY --from=selenium/ffmpeg:latest /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    echo "[+] APT Installing extractor dependencies for $TARGETPLATFORM..." \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        git ffmpeg ripgrep \
        # Packages we have also needed in the past:
        # youtube-dl wget2 aria2 python3-pyxattr rtmpdump libfribidi-bin mpv \
        # curl wget (already installed above)
    && rm -rf /var/lib/apt/lists/* \
    # Save version info
    && ( \
        which curl && curl --version | head -n1 \
        && which wget && wget --version 2>&1 | head -n1 \
        && which git && git --version 2>&1 | head -n1 \
        && which ffmpeg && (ffmpeg --version 2>&1 | head -n1) || true \
        && which rg && rg --version 2>&1 | head -n1 \
        && echo -e '\n\n' \
    ) | tee -a /VERSION.txt

# Install sonic search backend
COPY --from=archivebox/sonic:1.4.9 /usr/local/bin/sonic /usr/local/bin/sonic
COPY --chown=root:root --chmod=755 "etc/sonic.cfg" /etc/sonic.cfg
RUN (which sonic && sonic --version) | tee -a /VERSION.txt

######### Language Environments ####################################

# Set up Python environment
# NOT NEEDED because we're using a pre-built python image, keeping this here in case we switch back to custom-building our own:
#RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
#    --mount=type=cache,target=/root/.cache/pip,sharing=locked,id=pip-$TARGETARCH$TARGETVARIANT \
# RUN echo "[+] APT Installing PYTHON $PYTHON_VERSION for $TARGETPLATFORM (skipped, provided by base image)..." \
    # && apt-get update -qq \
    # && apt-get install -qq -y --no-upgrade \
    #     python${PYTHON_VERSION} python${PYTHON_VERSION}-minimal python3-pip python${PYTHON_VERSION}-venv pipx \
    # && rm -rf /var/lib/apt/lists/* \
    # tell PDM to allow using global system python site packages
    # && rm /usr/lib/python3*/EXTERNALLY-MANAGED \
    # && ln -s "$(which python${PYTHON_VERSION})" /usr/bin/python \
    # create global virtual environment GLOBAL_VENV to use (better than using pip install --global)
    # && python3 -m venv --system-site-packages --symlinks $GLOBAL_VENV \
    # && python3 -m venv --system-site-packages $GLOBAL_VENV \
    # && python3 -m venv $GLOBAL_VENV \
    # install global dependencies / python build dependencies in GLOBAL_VENV
    # && pip install --upgrade pip setuptools wheel \
    # Save version info
    # && ( \
    #     which python3 && python3 --version | grep " $PYTHON_VERSION" \
    #     && which pip && pip --version \
    #     # && which pdm && pdm --version \
    #     && echo -e '\n\n' \
    # ) | tee -a /VERSION.txt


# Set up Node environment
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    --mount=type=cache,target=/root/.npm,sharing=locked,id=npm-$TARGETARCH$TARGETVARIANT \
    echo "[+] APT Installing NODE $NODE_VERSION for $TARGETPLATFORM..." \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_VERSION}.x nodistro main" >> /etc/apt/sources.list.d/nodejs.list \
    && curl -fsSL "https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key" | gpg --dearmor | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && apt-get update -qq \
    && apt-get install -qq -y --no-upgrade libatomic1 \
    && apt-get install -y --no-upgrade \
        nodejs \
    && rm -rf /var/lib/apt/lists/* \
    # Update NPM to latest version
    && npm i -g npm --cache /root/.npm \
    # Save version info
    && ( \
        which node && node --version \
        && which npm && npm --version \
        && echo -e '\n\n' \
    ) | tee -a /VERSION.txt


# Set up uv and main app /venv
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/venv
WORKDIR "$CODE_DIR"
# COPY --chown=root:root --chmod=755 pyproject.toml "$CODE_DIR/"
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked,id=uv-$TARGETARCH$TARGETVARIANT \
    echo "[+] UV Creating /venv using python ${PYTHON_VERSION} for ${TARGETPLATFORM} (provided by base image)..." \
    && uv venv /venv
ENV VIRTUAL_ENV=/venv PATH="/venv/bin:$PATH"
RUN uv pip install setuptools pip \
    && ( \
        which python3 && python3 --version \
        && which uv && uv version \
        && echo -e '\n\n' \
    ) | tee -a /VERSION.txt


######### ArchiveBox & Extractor Dependencies ##################################

# Install ArchiveBox C-compiled/apt-installed Python dependencies in app /venv (currently only used for python-ldap)
WORKDIR "$CODE_DIR"
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    --mount=type=cache,target=/root/.cache/uv,sharing=locked,id=uv-$TARGETARCH$TARGETVARIANT \
    #--mount=type=cache,target=/root/.cache/pip,sharing=locked,id=pip-$TARGETARCH$TARGETVARIANT \
    echo "[+] APT Installing + Compiling python3-ldap for PIP archivebox[ldap] on ${TARGETPLATFORM}..." \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        build-essential gcc \
        python3-dev libssl-dev libldap2-dev libsasl2-dev python3-ldap \
        python3-msgpack python3-mutagen python3-regex python3-pycryptodome procps \
    && uv pip install \
        "python-ldap>=3.4.3" \
    && apt-get purge -y \
        python3-dev build-essential gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*


# Install apt font & rendering dependencies for chromium browser
# TODO: figure out how much of this overlaps with `playwright install-deps chromium`
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    echo "[+] APT Installing CHROMIUM dependencies, fonts, and display libraries for $TARGETPLATFORM..." \
    && apt-get update -qq \
    && apt-get install -qq -y \
        fontconfig fonts-ipafont-gothic fonts-wqy-zenhei fonts-thai-tlwg fonts-khmeros fonts-kacst fonts-symbola fonts-noto fonts-freefont-ttf \
        at-spi2-common fonts-liberation fonts-noto-color-emoji fonts-tlwg-loma-otf fonts-unifont libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libavahi-client3 \
        libavahi-common-data libavahi-common3 libcups2 libfontenc1 libice6 libnspr4 libnss3 libsm6 libunwind8 \
        libxaw7 libxcomposite1 libxdamage1 libxfont2 \
        libxkbfile1 libxmu6 libxpm4 libxt6 x11-xkb-utils x11-utils xfonts-encodings \
        # xfonts-scalable xfonts-utils xserver-common xvfb \
        # chrome can run without dbus/upower technically, it complains about missing dbus but should run ok anyway
        # libxss1 dbus dbus-x11 upower \
    # && service dbus start \
    && rm -rf /var/lib/apt/lists/*

# Install chromium browser binary using playwright
RUN --mount=type=cache,target=/root/.cache/ms-playwright,sharing=locked,id=browsers-$TARGETARCH$TARGETVARIANT \
    # --mount=type=cache,target=/root/.cache/pip,sharing=locked,id=pip-$TARGETARCH$TARGETVARIANT \
    --mount=type=cache,target=/root/.cache/uv,sharing=locked,id=uv-$TARGETARCH$TARGETVARIANT \
    echo "[+] PIP Installing playwright into /venv and CHROMIUM binary into $PLAYWRIGHT_BROWSERS_PATH..." \
    && uv pip install "playwright>=1.49.1" \
    && uv run playwright install chromium --no-shell \  
    # --with-deps \
    && export CHROME_BINARY="$(uv run python -c 'from playwright.sync_api import sync_playwright; print(sync_playwright().start().chromium.executable_path)')" \
    && ln -s "$CHROME_BINARY" /usr/bin/chromium-browser \
    && mkdir -p "/home/${ARCHIVEBOX_USER}/.config/chromium/Crash Reports/pending/" \
    && chown -R "$DEFAULT_PUID:$DEFAULT_PGID" "/home/${ARCHIVEBOX_USER}/.config" \
    && mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" \
    && chown -R $ARCHIVEBOX_USER "$PLAYWRIGHT_BROWSERS_PATH" \
    # delete extra full copy of node that playwright installs (saves >100mb)
    && rm -f /venv/lib/python$PYTHON_VERSION/site-packages/playwright/driver/node \
    # Save version info
    && ( \
        uv pip show playwright \
        # && uv run playwright --version \
        && which chromium-browser && /usr/bin/chromium-browser --version || /usr/lib/chromium/chromium --version \
        && echo -e '\n\n' \
    ) | tee -a /VERSION.txt

# Install Node extractor dependencies
ENV PATH="/home/$ARCHIVEBOX_USER/.npm/bin:$PATH"
USER $ARCHIVEBOX_USER
WORKDIR "/home/$ARCHIVEBOX_USER/.npm"
RUN --mount=type=cache,target=/home/archivebox/.npm_cache,sharing=locked,id=npm-$TARGETARCH$TARGETVARIANT,uid=$DEFAULT_PUID,gid=$DEFAULT_PGID \
    echo "[+] NPM Installing node extractor dependencies into /home/$ARCHIVEBOX_USER/.npm..." \
    && npm config set prefix "/home/$ARCHIVEBOX_USER/.npm" \
    && npm install --global --prefer-offline --no-fund --no-audit --cache "/home/$ARCHIVEBOX_USER/.npm_cache" \
        "@postlight/parser@^2.2.3" \
        "readability-extractor@github:ArchiveBox/readability-extractor" \
        "single-file-cli@^1.1.54" \
        "puppeteer@^23.5.0" \
        "@puppeteer/browsers@^2.4.0" \
    && rm -Rf "/home/$ARCHIVEBOX_USER/.cache/puppeteer"
USER root
WORKDIR "$CODE_DIR"
RUN ( \
        which node && node --version \
        && which npm && npm version \
        && which postlight-parser \
        && which readability-extractor && readability-extractor --version \
        && which single-file && single-file --version \
        && which puppeteer && puppeteer --version \
        && echo -e '\n\n' \
    ) | tee -a /VERSION.txt

######### Build Dependencies ####################################


# Install ArchiveBox Python venv dependencies from uv.lock
RUN --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    --mount=type=cache,target=/root/.cache/uv,sharing=locked,id=uv-$TARGETARCH$TARGETVARIANT \
    echo "[+] PIP Installing ArchiveBox dependencies from pyproject.toml and uv.lock..." \
    && uv sync \
        --frozen \
        --inexact \
        --all-extras \
        --no-install-project \
        --no-install-workspace
    # installs the pip packages that archivebox depends on, defined in pyproject.toml and uv.lock dependencies

# Install ArchiveBox Python package + workspace dependencies from source
COPY --chown=root:root --chmod=755 "." "$CODE_DIR/"
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked,id=uv-$TARGETARCH$TARGETVARIANT \
    echo "[*] Installing ArchiveBox Python source code from $CODE_DIR..." \
    && uv sync \
        --frozen \
        --inexact \
        --all-extras \
    && ( \
        uv tree \
        && which archivebox \
        && echo -e '\n\n' \
    ) | tee -a /VERSION.txt
    # installs archivebox itself, and any other vendored packages in pkgs/*, defined in pyproject.toml workspaces

####################################################

# Setup ArchiveBox runtime config
ENV TMP_DIR=/tmp/archivebox \
    LIB_DIR=/usr/share/archivebox/lib \
    GOOGLE_API_KEY=no \
    GOOGLE_DEFAULT_CLIENT_ID=no \
    GOOGLE_DEFAULT_CLIENT_SECRET=no

WORKDIR "$DATA_DIR"
RUN openssl rand -hex 16 > /etc/machine-id \
    && mkdir -p "$TMP_DIR" \
    && chown -R "$DEFAULT_PUID:$DEFAULT_PGID" "$TMP_DIR" \
    && mkdir -p "$LIB_DIR" \
    && chown -R "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR" \
    && echo -e "\nTMP_DIR=$TMP_DIR\nLIB_DIR=$LIB_DIR\nMACHINE_ID=$(cat /etc/machine-id)\n" | tee -a /VERSION.txt

# Print version for nice docker finish summary
RUN (echo -e "\n\n[√] Finished Docker build succesfully. Saving build summary in: /VERSION.txt" \
    && echo -e "PLATFORM=${TARGETPLATFORM} ARCH=$(uname -m) ($(uname -s) ${TARGETARCH} ${TARGETVARIANT})\n" \
    && echo -e "BUILD_END_TIME=$(date +"%Y-%m-%d %H:%M:%S %s")\n\n" \
    ) | tee -a /VERSION.txt

# Run   $ archivebox version                                >> /VERSION.txt
# RUN "$CODE_DIR"/bin/docker_entrypoint.sh init 2>&1 | tee -a /VERSION.txt
RUN "$CODE_DIR"/bin/docker_entrypoint.sh version 2>&1 | tee -a /VERSION.txt

####################################################

# Expose ArchiveBox's main interfaces to the outside world
WORKDIR "$DATA_DIR"
VOLUME "$DATA_DIR"
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=20s --retries=15 \
    CMD curl --silent 'http://localhost:8000/health/' | grep -q 'OK'

ENTRYPOINT ["dumb-init", "--", "/app/bin/docker_entrypoint.sh"]
CMD ["archivebox", "server", "--quick-init", "0.0.0.0:8000"]

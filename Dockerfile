# This is the Dockerfile for ArchiveBox, it bundles the following dependencies:
#     python3, ArchiveBox, curl, wget, git, chromium, youtube-dl, yt-dlp, single-file
# Usage:
#     git submodule update --init --recursive
#     git pull --recurse-submodules
#     docker build . -t archivebox --no-cache
#     docker run -v "$PWD/data":/data archivebox init
#     docker run -v "$PWD/data":/data archivebox add 'https://example.com'
#     docker run -v "$PWD/data":/data -it archivebox manage createsuperuser
#     docker run -v "$PWD/data":/data -p 8000:8000 archivebox server
# Multi-arch build:
#     docker buildx create --use
#     docker buildx build . --platform=linux/amd64,linux/arm64,linux/arm/v7 --push -t archivebox/archivebox:latest -t archivebox/archivebox:dev
#
# Read more about [developing
# Archivebox](https://github.com/ArchiveBox/ArchiveBox#archivebox-development).


FROM debian:bookworm-backports

LABEL name="archivebox" \
    maintainer="Nick Sweeting <dockerfile@archivebox.io>" \
    description="All-in-one personal internet archiving container" \
    homepage="https://github.com/ArchiveBox/ArchiveBox" \
    documentation="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#docker"

######### Base System Setup ####################################

# Global system-level config
ENV TZ=UTC \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 \
    npm_config_loglevel=error

# Application-level config
ENV CODE_DIR=/app \
    DATA_DIR=/data \
    GLOBAL_VENV=/venv \
    APP_VENV=/app/.venv \
    NODE_MODULES=/app/node_modules \
    ARCHIVEBOX_USER="archivebox"

ENV PATH="$PATH:$GLOBAL_VENV/bin:$APP_VENV/bin:$NODE_MODULES/.bin"


# Create non-privileged user for archivebox and chrome
RUN echo "[*] Setting up system environment..." \
    && groupadd --system $ARCHIVEBOX_USER \
    && useradd --system --create-home --gid $ARCHIVEBOX_USER --groups audio,video $ARCHIVEBOX_USER \
    && mkdir -p /etc/apt/keyrings

# Install system apt dependencies (adding backports to access more recent apt updates)
RUN echo "[+] Installing system dependencies..." \
    && echo 'deb https://deb.debian.org/debian bullseye-backports main contrib non-free' >> /etc/apt/sources.list.d/backports.list \
    && apt-get update -qq \
    && apt-get install -qq -y \
        apt-transport-https ca-certificates gnupg2 curl wget \
        zlib1g-dev dumb-init gosu cron unzip \
        nano iputils-ping dnsutils htop procps \
        # 1. packaging dependencies
        # 2. docker and init system dependencies
        # 3. frivolous CLI helpers to make debugging failed archiving easier
    && mkdir -p /etc/apt/keyrings \
    && rm -rf /var/lib/apt/lists/*


######### Language Environments ####################################

# Install Node environment
RUN echo "[+] Installing Node environment..." \
    && echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main' >> /etc/apt/sources.list.d/nodejs.list \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && apt-get update -qq \
    && apt-get install -qq -y nodejs \
    && npm i -g npm \
    && node --version \
    && npm --version

# Install Python environment
RUN echo "[+] Installing Python environment..." \
    && apt-get update -qq \
    && apt-get install -qq -y -t bookworm-backports --no-install-recommends \
        python3 python3-pip python3-venv python3-setuptools python3-wheel python-dev-is-python3 \
        python3-ldap libldap2-dev libsasl2-dev libssl-dev \
    && rm /usr/lib/python3*/EXTERNALLY-MANAGED \
    && python3 -m venv --system-site-packages --symlinks $GLOBAL_VENV \
    && $GLOBAL_VENV/bin/pip install --upgrade pip pdm setuptools wheel python-ldap \
    && rm -rf /var/lib/apt/lists/*

######### Extractor Dependencies ##################################

# Install apt dependencies
RUN echo "[+] Installing extractor APT dependencies..." \
    && apt-get update -qq \
    && apt-get install -qq -y -t bookworm-backports --no-install-recommends \
        curl wget git yt-dlp ffmpeg ripgrep \
        # Packages we have also needed in the past:
        # youtube-dl wget2 aria2 python3-pyxattr rtmpdump libfribidi-bin mpv \
        # fontconfig fonts-ipafont-gothic fonts-wqy-zenhei fonts-thai-tlwg fonts-kacst fonts-symbola fonts-noto fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Install chromium browser using playwright
ENV PLAYWRIGHT_BROWSERS_PATH="/browsers"
RUN echo "[+] Installing extractor Chromium dependency..." \
    && apt-get update -qq \
    && $GLOBAL_VENV/bin/pip install playwright \
    && $GLOBAL_VENV/bin/playwright install --with-deps chromium \
    && CHROME_BINARY="$($GLOBAL_VENV/bin/python -c 'from playwright.sync_api import sync_playwright; print(sync_playwright().start().chromium.executable_path)')" \
    && ln -s "$CHROME_BINARY" /usr/bin/chromium-browser \
    && mkdir -p "/home/${ARCHIVEBOX_USER}/.config/chromium/Crash Reports/pending/" \
    && chown -R $ARCHIVEBOX_USER "/home/${ARCHIVEBOX_USER}/.config"

# Install Node dependencies
WORKDIR "$CODE_DIR"
COPY --chown=root:root --chmod=755 "package.json" "package-lock.json" "$CODE_DIR/"
RUN echo "[+] Installing extractor Node dependencies..." \
    && npm ci --prefer-offline --no-audit \
    && npm version

######### Build Dependencies ####################################

# # Installing Python dependencies to build from source
# WORKDIR "$CODE_DIR"
# COPY --chown=root:root --chmod=755 "./pyproject.toml" "./pdm.lock" "$CODE_DIR/"
# RUN echo "[+] Installing project Python dependencies..." \
#     && apt-get update -qq \
#     && apt-get install -qq -y -t bookworm-backports --no-install-recommends \
#         build-essential libssl-dev libldap2-dev libsasl2-dev \
#     && pdm use -f $GLOBAL_VENV \
#     && pdm install --fail-fast --no-lock --group :all --no-self \
#     && pdm build \
#     && apt-get purge -y \
#         build-essential libssl-dev libldap2-dev libsasl2-dev \
#         # these are only needed to build CPython libs, we discard after build phase to shrink layer size
#     && apt-get autoremove -y \
#     && rm -rf /var/lib/apt/lists/*

# Install ArchiveBox Python package from source
COPY --chown=root:root --chmod=755 "." "$CODE_DIR/"
RUN echo "[*] Installing ArchiveBox package from /app..." \
    && apt-get update -qq \
    && $GLOBAL_VENV/bin/pip install -e "$CODE_DIR"[sonic,ldap]

####################################################

# Setup ArchiveBox runtime config
WORKDIR "$DATA_DIR"
ENV IN_DOCKER=True \
    WGET_BINARY="wget" \
    YOUTUBEDL_BINARY="yt-dlp" \
    CHROME_SANDBOX=False \
    CHROME_BINARY="/usr/bin/chromium-browser" \
    USE_SINGLEFILE=True \
    SINGLEFILE_BINARY="$NODE_MODULES/.bin/single-file" \
    USE_READABILITY=True \
    READABILITY_BINARY="$NODE_MODULES/.bin/readability-extractor" \
    USE_MERCURY=True \
    MERCURY_BINARY="$NODE_MODULES/.bin/postlight-parser"

# Print version for nice docker finish summary
# RUN archivebox version
RUN echo "[√] Finished Docker build succesfully. Saving build summary in: /version_info.txt" \
    && uname -a | tee -a /version_info.txt \
    && env --chdir="$NODE_DIR" npm version | tee -a /version_info.txt \
    && env --chdir="$CODE_DIR" pdm info | tee -a /version_info.txt \
    && "$CODE_DIR/bin/docker_entrypoint.sh" archivebox version 2>&1 | tee -a /version_info.txt

####################################################

# Open up the interfaces to the outside world
VOLUME "/data"
EXPOSE 8000

# Optional:
# HEALTHCHECK --interval=30s --timeout=20s --retries=15 \
#     CMD curl --silent 'http://localhost:8000/admin/login/' || exit 1

ENTRYPOINT ["dumb-init", "--", "/app/bin/docker_entrypoint.sh"]
CMD ["archivebox", "server", "--quick-init", "0.0.0.0:8000"]

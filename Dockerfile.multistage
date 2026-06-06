# syntax=docker/dockerfile:1.7

# Multistage ArchiveBox Dockerfile that consumes the abx-dl runtime image.
# abx-dl owns Python, Node, Chromium, and downloader plugin runtimes.
# ArchiveBox owns ripgrep, sonic, supervisor, Django, and the app runtime.
# Build abx-dl first, then point this file at it:
#   docker buildx build ../abx-dl -f ../abx-dl/Dockerfile \
#       --build-context abxbus=../abxbus \
#       --build-context abxpkg=../abxpkg \
#       --build-context abx-plugins=../abx-plugins \
#       -t archivebox/abx-dl:dev
#   docker buildx build . -f Dockerfile \
#       --build-arg ABX_DL_IMAGE=archivebox/abx-dl:latest \
#       -t archivebox:multistage

ARG ABX_DL_IMAGE=archivebox/abx-dl:latest

FROM ${ABX_DL_IMAGE} AS abx-dl
FROM archivebox/sonic:1.4.9 AS sonic
FROM ubuntu:24.04 AS archivebox-runtime-base

ARG TARGETPLATFORM
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT

ENV TZ=UTC \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ONLY_BINARY=aiohttp \
    npm_config_loglevel=error

ENV PYTHON_VERSION=3.13 \
    NODE_VERSION=22.22.3

ENV ARCHIVEBOX_USER=archivebox \
    DEFAULT_PUID=911 \
    DEFAULT_PGID=911 \
    IN_DOCKER=True

ENV CODE_DIR=/app \
    DATA_DIR=/data \
    LIB_DIR=/opt/archivebox/lib \
    ABXPKG_LIB_DIR=/opt/archivebox/lib \
    PLAYWRIGHT_BROWSERS_PATH=/opt/archivebox/lib/playwright/cache \
    PERSONAS_DIR=/data/personas \
    CHROME_USER_DATA_DIR=/data/personas/Default/chrome_profile \
    CHROME_HEADLESS=true \
    CHROME_SANDBOX=false \
    CHROME_ISOLATION=crawl \
    CHROME_ARGS_EXTRA='["--disable-gpu","--disable-features=Translate,OptimizationGuideModelDownloading,MediaRouter"]'

ENV TMP_DIR=/tmp/archivebox \
    PIP_VENV_PYTHON=/venv/bin/python3 \
    GOOGLE_API_KEY=no \
    GOOGLE_DEFAULT_CLIENT_ID=no \
    GOOGLE_DEFAULT_CLIENT_SECRET=no

ENV UV_COMPILE_BYTECODE=0 \
    UV_PYTHON_PREFERENCE=managed \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/venv \
    VIRTUAL_ENV=/venv \
    PATH="/venv/bin:/opt/node/bin:/opt/archivebox/lib/bin:$PATH"

SHELL ["/bin/bash", "-o", "pipefail", "-o", "errexit", "-o", "errtrace", "-o", "nounset", "-c"]
WORKDIR "$CODE_DIR"

RUN echo 'Binary::apt::APT::Keep-Downloaded-Packages "1";' > /etc/apt/apt.conf.d/99keep-cache \
    && echo 'APT::Install-Recommends "0";' > /etc/apt/apt.conf.d/99no-install-recommends \
    && echo 'APT::Install-Suggests "0";' > /etc/apt/apt.conf.d/99no-install-suggests \
    && rm -f /etc/apt/apt.conf.d/docker-clean

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    echo "[+] APT Installing ArchiveBox base runtime dependencies for $TARGETPLATFORM..." \
    && apt-get update -qq \
    && apt-get install -qq -y \
        apt-transport-https apt-utils ca-certificates curl wget gnupg2 \
        dumb-init util-linux unzip git grep ripgrep dnsutils iputils-ping procps tree nano \
        cron openssl xz-utils zlib1g libldap2 libsasl2-2 libssl3 libsqlite3-0 \
        libasound2t64 libatk-bridge2.0-0 libatk1.0-0 libcairo2 libcups2 \
        libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 \
        libpango-1.0-0 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 \
        libxext6 libxfixes3 libxkbcommon0 libxrandr2 libxshmfence1 \
        fonts-liberation fonts-noto-color-emoji xdg-utils \
        ffmpeg imagemagick tesseract-ocr tesseract-ocr-eng openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Runtime-owned layers copied from the abx-dl image.
COPY --from=abx-dl /bin/uv /bin/uv
COPY --from=abx-dl /opt/uv/python /opt/uv/python
COPY --from=abx-dl /opt/node /opt/node
COPY --from=abx-dl /VERSION.txt /ABX-DL-VERSION.txt

RUN (echo "[i] Docker build for ArchiveBox multistage starting..." \
    && echo "PLATFORM=${TARGETPLATFORM} ARCH=$(uname -m) (${TARGETARCH} ${TARGETVARIANT})" \
    && echo "BUILD_START_TIME=$(date +"%Y-%m-%d %H:%M:%S %s") TZ=${TZ} LANG=${LANG}" \
    && uname -a \
    && sed -n '1,7p' /etc/os-release \
    && which node && node --version \
    && which uv && uv self version \
    ) | tee -a /VERSION.txt

ENV PYTHONDONTWRITEBYTECODE=1

FROM archivebox-runtime-base AS archivebox-builder

WORKDIR "$CODE_DIR"
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-$TARGETARCH$TARGETVARIANT \
    --mount=type=cache,target=/root/.cache/uv,sharing=locked,id=uv-$TARGETARCH$TARGETVARIANT \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    echo "[+] UV Installing ArchiveBox dependencies from pyproject.toml..." \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        build-essential gcc libldap2-dev libsasl2-dev libssl-dev \
    && uv venv /venv --python "${PYTHON_VERSION}" \
    && uv pip install setuptools pip wheel \
    && uv sync \
        --refresh \
        --no-dev \
        --inexact \
        --all-extras \
        --no-install-project \
        --no-install-workspace \
        --no-sources \
    && apt-get purge -y build-essential gcc libldap2-dev libsasl2-dev libssl-dev \
    && apt-get autoremove -y \
    && find /venv -type d -name __pycache__ -prune -exec rm -rf {} + \
    && find /venv -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=root:root --chmod=755 "." "$CODE_DIR/"
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked,id=uv-$TARGETARCH$TARGETVARIANT \
    echo "[*] Installing ArchiveBox Python source code from $CODE_DIR..." \
    && COMMIT_HASH="$( \
        if [[ -f "$CODE_DIR/.git/HEAD" ]]; then \
            HEAD_REF="$(cat "$CODE_DIR/.git/HEAD")"; \
            if [[ "$HEAD_REF" =~ ^[0-9a-fA-F]{40}$ ]]; then \
                echo "$HEAD_REF"; \
            elif [[ "$HEAD_REF" == ref:\ * ]]; then \
                REF_PATH="${HEAD_REF#ref: }"; \
                cat "$CODE_DIR/.git/$REF_PATH" 2>/dev/null || awk -v ref="$REF_PATH" '$2 == ref {print $1}' "$CODE_DIR/.git/packed-refs" 2>/dev/null || true; \
            fi; \
        fi)" \
    && if [[ "$COMMIT_HASH" =~ ^[0-9a-fA-F]{40}$ ]]; then echo "COMMIT_HASH=$COMMIT_HASH" | tee -a /VERSION.txt; fi \
    && uv pip install --no-deps "$CODE_DIR" \
    && (uv pip show archivebox && which archivebox) | tee -a /VERSION.txt \
    && find /venv "$CODE_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + \
    && find /venv "$CODE_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete \
    && rm -rf "$CODE_DIR/.git"

FROM archivebox-runtime-base

LABEL name="archivebox" \
    maintainer="Nick Sweeting <dockerfile@archivebox.io>" \
    description="All-in-one self-hosted internet archiving solution" \
    homepage="https://github.com/ArchiveBox/ArchiveBox" \
    documentation="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker" \
    org.opencontainers.image.title="ArchiveBox" \
    org.opencontainers.image.vendor="ArchiveBox" \
    org.opencontainers.image.description="All-in-one self-hosted internet archiving solution" \
    org.opencontainers.image.source="https://github.com/ArchiveBox/ArchiveBox" \
    com.docker.image.source.entrypoint="Dockerfile"

COPY --from=sonic /usr/local/bin/sonic /usr/local/bin/sonic
COPY --chown=root:root --chmod=755 "etc/sonic.cfg" /etc/sonic.cfg

COPY --from=archivebox-builder /opt/uv/python /opt/uv/python
COPY --from=archivebox-builder /venv /venv
COPY --from=archivebox-builder /app /app
COPY --from=archivebox-builder /VERSION.txt /VERSION.txt
COPY --from=abx-dl --chown=911:911 /opt/archivebox/lib /opt/archivebox/lib

RUN echo "[*] Setting up $ARCHIVEBOX_USER user uid=${DEFAULT_PUID}..." \
    && groupadd --system "$ARCHIVEBOX_USER" \
    && useradd --system --create-home --gid "$ARCHIVEBOX_USER" --groups audio,video "$ARCHIVEBOX_USER" \
    && usermod -u "$DEFAULT_PUID" "$ARCHIVEBOX_USER" \
    && groupmod -g "$DEFAULT_PGID" "$ARCHIVEBOX_USER" \
    && (which sonic && sonic --version) | tee -a /VERSION.txt \
    && install -d -o "$DEFAULT_PUID" -g "$DEFAULT_PGID" "$DATA_DIR" "$TMP_DIR" "$LIB_DIR" "$PLAYWRIGHT_BROWSERS_PATH" \
    && chown "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR" "$PLAYWRIGHT_BROWSERS_PATH" \
    && install -d -o "$DEFAULT_PUID" -g "$DEFAULT_PGID" "/home/$ARCHIVEBOX_USER/.config/abx" "/home/$ARCHIVEBOX_USER/.cache/abxbus" "/home/$ARCHIVEBOX_USER/.cache/uv" \
    && openssl rand -hex 16 > /etc/machine-id \
    && echo -e "\nARCHIVEBOX_USER=$ARCHIVEBOX_USER PUID=$(id -u "$ARCHIVEBOX_USER") PGID=$(id -g "$ARCHIVEBOX_USER")" | tee -a /VERSION.txt \
    && echo -e "TMP_DIR=$TMP_DIR\nLIB_DIR=$LIB_DIR\nPLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH\nMACHINE_ID=$(cat /etc/machine-id)\n" | tee -a /VERSION.txt

WORKDIR "$DATA_DIR"
RUN echo "[+] Initializing image collection..." \
    && find "$DATA_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} + \
    && PUID=0 PGID=0 archivebox init \
    && find "$DATA_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + \
    && find "$DATA_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete \
    && (chown "$DEFAULT_PUID:$DEFAULT_PGID" \
        "$DATA_DIR" "$DATA_DIR"/.archivebox_id "$DATA_DIR"/ArchiveBox.conf "$DATA_DIR"/index.sqlite3 \
        "$DATA_DIR"/logs "$DATA_DIR"/logs/* "$DATA_DIR"/sources \
        "$DATA_DIR"/archive "$DATA_DIR"/archive/users "$DATA_DIR"/personas \
        "$DATA_DIR"/tmp "$DATA_DIR"/tmp/* \
        2>/dev/null || true)

RUN chmod +x "$CODE_DIR"/bin/*.sh \
    && chmod g+w "$TMP_DIR" "$LIB_DIR" "$PLAYWRIGHT_BROWSERS_PATH" \
    && install -d -o "$DEFAULT_PUID" -g "$DEFAULT_PGID" "$LIB_DIR/pnpm/packages/opencode" \
    && env -u PNPM_HOME PATH="/opt/node/bin:$PATH" /opt/node/bin/corepack pnpm add --loglevel=error --store-dir="$TMP_DIR/pnpm-store" --config.dangerouslyAllowAllBuilds=true --dir="$LIB_DIR/pnpm/packages/opencode" opencode-ai 2>&1 | tee -a /VERSION.txt \
    && chown -R "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR/pnpm/packages/opencode" \
    && rm -rf "$TMP_DIR/pnpm-store" /root/.cache/node \
    && ln -sf "$LIB_DIR/pnpm/packages/opencode/node_modules/.bin/opencode" "$LIB_DIR/bin/opencode" \
    && ln -sf "$LIB_DIR/pnpm/packages/opencode/node_modules/.bin/opencode" "$LIB_DIR/env/bin/opencode" \
    && chown "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR" \
    && chown -h "$DEFAULT_PUID:$DEFAULT_PGID" "$LIB_DIR/bin/opencode" "$LIB_DIR/env/bin/opencode" \
    && GIT_BINARY="$LIB_DIR/env/bin/git" GALLERYDL_BINARY="$LIB_DIR/env/bin/gallery-dl" FORUMDL_BINARY="$LIB_DIR/env/bin/forum-dl" OPENCODE_BINARY="$LIB_DIR/env/bin/opencode" HOME="/home/$ARCHIVEBOX_USER" XDG_CONFIG_HOME="/home/$ARCHIVEBOX_USER/.config" XDG_CACHE_HOME="/home/$ARCHIVEBOX_USER/.cache" ABXPKG_INSTALL_TIMEOUT=600 ABXPKG_POSTINSTALL_SCRIPTS=True ABXPKG_MIN_RELEASE_AGE=0 TIMEOUT=600 setpriv --reuid="$ARCHIVEBOX_USER" --regid="$ARCHIVEBOX_USER" --init-groups archivebox install archivewebpage defuddle forumdl gallerydl git istilldontcareaboutcookies liteparse mercury opencode opendataloader papersdl parse_rss_urls readability search_backend_ripgrep search_backend_sonic 2>&1 | tee -a /VERSION.txt \
    && "$LIB_DIR/env/bin/chromium" --version | tee -a /VERSION.txt \
    && "$LIB_DIR/uv/packages/papers-dl/venv/bin/papers-dl" --version | tee -a /VERSION.txt \
    && /usr/bin/rg --version | head -1 | tee -a /VERSION.txt \
    && /usr/local/bin/sonic --version | tee -a /VERSION.txt \
    && /venv/bin/supervisord --version | tee -a /VERSION.txt \
    && ! command -v gcc \
    && ! command -v g++ \
    && ! command -v make \
    && HOME="/home/$ARCHIVEBOX_USER" XDG_CONFIG_HOME="/home/$ARCHIVEBOX_USER/.config" XDG_CACHE_HOME="/home/$ARCHIVEBOX_USER/.cache" setpriv --reuid="$ARCHIVEBOX_USER" --regid="$ARCHIVEBOX_USER" --init-groups archivebox version 2>&1 | tee -a /VERSION.txt \
    && find /venv "$CODE_DIR" "$LIB_DIR" "$DATA_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + \
    && find /venv "$CODE_DIR" "$LIB_DIR" "$DATA_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete \
    && rm -rf /root/.cache /var/cache/apt/* /var/lib/apt/lists/*

RUN (echo -e "\n\n[√] Finished ArchiveBox multistage Docker build successfully." \
    && echo -e "PLATFORM=${TARGETPLATFORM} ARCH=$(uname -m) (${TARGETARCH} ${TARGETVARIANT})" \
    && echo -e "BUILD_END_TIME=$(date +"%Y-%m-%d %H:%M:%S %s")\n\n" \
    ) | tee -a /VERSION.txt

WORKDIR "$DATA_DIR"
VOLUME "$DATA_DIR"
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=20s --retries=15 \
    CMD curl --fail --silent --show-error --max-time 5 --connect-timeout 2 'http://admin.archivebox.localhost:8000/health/' | grep -q 'OK'

ENTRYPOINT ["dumb-init", "--", "/app/bin/docker_entrypoint.sh"]
CMD ["archivebox", "server", "--init", "0.0.0.0:8000"]

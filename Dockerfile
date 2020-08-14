# This is the Dockerfile for ArchiveBox, it bundles the following dependencies:
#     python3, ArchiveBox, curl, wget, git, chromium, youtube-dl, single-file
# Usage:
#     docker build . -t archivebox --no-cache
#     docker run -v "$PWD/data":/data archivebox init
#     docker run -v "$PWD/data":/data archivebox add 'https://example.com'
#     docker run -v "$PWD/data":/data -it archivebox manage createsuperuser
#     docker run -v "$PWD/data":/data -p 8000:8000 archivebox server

FROM python:3.8-slim-buster

LABEL name="archivebox" \
    maintainer="Nick Sweeting <archivebox-docker@sweeting.me>" \
    description="All-in-one personal internet archiving container" \
    homepage="https://github.com/pirate/ArchiveBox" \
    documentation="https://github.com/pirate/ArchiveBox/wiki/Docker#docker"

# System-level base config
ENV TZ=UTC \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1

# Application-level base config
ENV CODE_DIR=/app \
    VENV_PATH=/venv \
    DATA_DIR=/data \
    NODE_DIR=/node \
    ARCHIVEBOX_USER="archivebox"

# Create non-privileged user for archivebox and chrome
RUN groupadd --system $ARCHIVEBOX_USER \
    && useradd --system --create-home --gid $ARCHIVEBOX_USER --groups audio,video $ARCHIVEBOX_USER

# Install system dependencies
RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        apt-transport-https ca-certificates apt-utils gnupg gnupg2 libgconf-2-4 zlib1g-dev \
        dumb-init gosu unzip curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python environment
RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        ipython3 python-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Node environment
RUN curl -s https://deb.nodesource.com/gpgkey/nodesource.gpg.key | apt-key add - \
    && echo 'deb https://deb.nodesource.com/node_14.x buster main' >> /etc/apt/sources.list \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install apt dependencies
RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        wget curl chromium git ffmpeg youtube-dl \
        fontconfig fonts-ipafont-gothic fonts-wqy-zenhei fonts-thai-tlwg fonts-kacst fonts-symbola fonts-noto fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
WORKDIR "$CODE_DIR"
ENV PATH="${PATH}:$VENV_PATH/bin"
RUN python -m venv --clear --symlinks "$VENV_PATH" \
    && pip install --upgrade --quiet pip setuptools
ADD ./archivebox.egg-info/requires.txt "$CODE_DIR/archivebox.egg-info/requires.txt"
RUN grep -B 1000 -E '^$' "$CODE_DIR/archivebox.egg-info/requires.txt" | pip install --quiet -r /dev/stdin

# Install Node dependencies
WORKDIR "$NODE_DIR"
ENV PATH="${PATH}:$NODE_DIR/node_modules/.bin" \
    npm_config_loglevel=error
RUN npm install -g npm
ADD ./package.json ./package.json
RUN npm install

# Install ArchiveBox Python package
WORKDIR "$CODE_DIR"
ADD . "$CODE_DIR"
RUN pip install -e .

# Setup ArchiveBox runtime config
WORKDIR "$DATA_DIR"
ENV IN_DOCKER=True \
    CHROME_SANDBOX=False \
    CHROME_BINARY="chromium" \
    SINGLEFILE_BINARY="$NODE_DIR/node_modules/.bin/single-file" \
    READABILITY_BINARY="$NODE_DIR/node_modules/.bin/readability-extractor"

# Print version for nice docker finish summary
RUN archivebox version

# Open up the interfaces to the outside world
VOLUME "$DATA_DIR"
VOLUME "$CODE_DIR"
EXPOSE 8000

ENTRYPOINT ["dumb-init", "--", "/app/bin/docker_entrypoint.sh"]
CMD ["archivebox", "server", "0.0.0.0:8000"]

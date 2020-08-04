# This is the Dockerfile for ArchiveBox, it includes the following major pieces:
#     git, curl, wget, python3, youtube-dl, google-chrome-stable, ArchiveBox
# Usage:
#     docker build . -t archivebox
#     docker run -v "$PWD/data":/data archivebox init
#     docker run -v "$PWD/data":/data archivebox add 'https://example.com'
# Documentation:
#     https://github.com/pirate/ArchiveBox/wiki/Docker#docker

FROM python:3.8-slim-buster

LABEL name="archivebox" \
    maintainer="Nick Sweeting <archivebox-git@sweeting.me>" \
    description="All-in-one personal internet archiving container"

ENV TZ=UTC \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 \
    CODE_PATH=/app \
    VENV_PATH=/venv \
    DATA_PATH=/data \
    EXTRA_PATH=/extra

# First install CLI utils and base deps, then Chrome + Fons + nodejs
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
    apt-transport-https ca-certificates apt-utils gnupg gosu gnupg2 libgconf-2-4 zlib1g-dev \
    dumb-init jq git wget curl youtube-dl ffmpeg \
    && curl -sSL "https://dl.google.com/linux/linux_signing_key.pub" | apt-key add - \
    && echo "deb https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
    google-chrome-stable \
    fontconfig \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-thai-tlwg \
    fonts-kacst \
    fonts-symbola \
    fonts-noto \
    fonts-freefont-ttf \
    nodejs \
    unzip \
    && rm -rf /var/lib/apt/lists/* 

# Clone singlefile and move it to the /bin folder so archivebox can find it

WORKDIR "$EXTRA_PATH"
RUN wget -qO - https://github.com/gildas-lormeau/SingleFile/archive/master.zip > SingleFile.zip \
    && unzip -q SingleFile.zip \
    && npm install --prefix SingleFile-master/cli --production > /dev/null 2>&1 \
    && chmod +x SingleFile-master/cli/single-file 

# Run everything from here on out as non-privileged user
RUN groupadd --system archivebox \
    && useradd --system --create-home --gid archivebox --groups audio,video archivebox

ADD . "$CODE_PATH"
WORKDIR "$CODE_PATH"
ENV PATH="${PATH}:$VENV_PATH/bin"
RUN python -m venv --clear --symlinks "$VENV_PATH" \
    && pip install --upgrade pip setuptools \
    && pip install -e .

VOLUME "$DATA_PATH"
WORKDIR "$DATA_PATH"
EXPOSE 8000
ENV CHROME_BINARY=google-chrome \
    CHROME_SANDBOX=False \
    SINGLEFILE_BINARY="$EXTRA_PATH/SingleFile-master/cli/single-file"

RUN env ALLOW_ROOT=True archivebox version

ENTRYPOINT ["dumb-init", "--", "/app/bin/docker_entrypoint.sh", "archivebox"]
CMD ["server", "0.0.0.0:8000"]

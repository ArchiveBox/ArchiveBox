# This is the Dockerfile for ArchiveBox, it includes the following major pieces:
#     git, curl, wget, python3, youtube-dl, google-chrome-stable, ArchiveBox
# Usage:
#     docker build . -t archivebox:latest
#     docker run -v=./data:/data archivebox:latest init
#     docker run -v=./data:/data archivebox:latest add 'https://example.com'
# Documentation:
#     https://github.com/pirate/ArchiveBox/wiki/Docker#docker

FROM python:3.8-slim-buster
LABEL name="archivebox" \
      maintainer="Nick Sweeting <archivebox-git@sweeting.me>" \
      version="0.4.3" \
      description="All-in-one personal internet archiving container"

ENV LANG=C.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 \
    CODE_PATH=/app \
    VENV_PATH=/venv \
    DATA_PATH=/data

# Install latest chrome package and fonts to support major charsets (Chinese, Japanese, Arabic, Hebrew, Thai and a few others)
RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
       apt-transport-https ca-certificates apt-utils gnupg gnupg2 libgconf-2-4 zlib1g-dev dumb-init \
       wget curl youtube-dl jq git ffmpeg avconv \
    && curl -sSL https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
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
    && rm -rf /var/lib/apt/lists/*

# Add user so we don't need --no-sandbox to run chrome
RUN groupadd -r archivebox && useradd -r -g archivebox -G audio,video archivebox \
    && mkdir -p /home/archivebox/Downloads \
    && chown -R archivebox:archivebox /home/archivebox

WORKDIR "$CODE_PATH"
ADD . "$CODE_PATH"
VOLUME "$CODE_PATH"
RUN chown -R archivebox:archivebox "$CODE_PATH"

ENV PATH="$VENV_PATH/bin:${PATH}"
RUN python --version \
    && python -m venv "$VENV_PATH" \
    && pip install --upgrade pip \
    && pip install -e . \
    && chown -R archivebox:archivebox "$VENV_PATH"

WORKDIR "$DATA_PATH"
VOLUME "$DATA_PATH"
RUN chown -R archivebox:archivebox "$DATA_PATH"

# Run everything from here on out as non-privileged user
USER archivebox
ENV CHROME_BINARY=google-chrome \
    CHROME_SANDBOX=False \
    OUTPUT_DIR="$DATA_PATH"

RUN archivebox version

ENTRYPOINT ["dumb-init", "--"]
CMD ["archivebox"]

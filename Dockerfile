# This Dockerfile for ArchiveBox installs the following in a container:
#     - curl, wget, python3, youtube-dl, google-chrome-unstable
#     - ArchiveBox
# Usage:
#     docker build github.com/pirate/ArchiveBox -t archivebox
#     echo 'https://example.com' | docker run -i --mount type=bind,source=./data,target=/data archivebox /bin/archive
#     docker run --mount type=bind,source=./data,target=/data archivebox /bin/archive 'https://example.com/some/rss/feed.xml'
# Documentation:
#     https://github.com/pirate/ArchiveBox/wiki/Docker#docker

FROM node:11-slim
LABEL maintainer="Nick Sweeting <archivebox-git@sweeting.me>"

RUN apt-get update \
    && apt-get install -yq --no-install-recommends \
        git wget curl youtube-dl gnupg2 libgconf-2-4 python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install latest chrome package and fonts to support major charsets (Chinese, Japanese, Arabic, Hebrew, Thai and a few others)
RUN apt-get update && apt-get install -y wget --no-install-recommends \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list' \
    && apt-get update \
    && apt-get install -y google-chrome-unstable fonts-ipafont-gothic fonts-wqy-zenhei fonts-thai-tlwg fonts-kacst ttf-freefont \
      --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /src/*.deb

# It's a good idea to use dumb-init to help prevent zombie chrome processes.
ADD https://github.com/Yelp/dumb-init/releases/download/v1.2.0/dumb-init_1.2.0_amd64 /usr/local/bin/dumb-init
RUN chmod +x /usr/local/bin/dumb-init

# Uncomment to skip the chromium download when installing puppeteer. If you do,
# you'll need to launch puppeteer with:
#     browser.launch({executablePath: 'google-chrome-unstable'})
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD true

# Install puppeteer so it's available in the container.
RUN npm i puppeteer

# Add user so we don't need --no-sandbox.
RUN groupadd -r pptruser && useradd -r -g pptruser -G audio,video pptruser \
    && mkdir -p /home/pptruser/Downloads \
    && chown -R pptruser:pptruser /home/pptruser \
    && chown -R pptruser:pptruser /node_modules

# Install the ArchiveBox repository and pip requirements
RUN git clone https://github.com/pirate/ArchiveBox /home/pptruser/app \
    && mkdir -p /data \
    && chown -R pptruser:pptruser /data \
    && ln -s /data /home/pptruser/app/archivebox/output \
    && ln -s /home/pptruser/app/bin/* /bin/ \
    && ln -s /home/pptruser/app/bin/archivebox /bin/archive \
    && chown -R pptruser:pptruser /home/pptruser/app/archivebox
    # && pip3 install -r /home/pptruser/app/archivebox/requirements.txt

VOLUME /data

ENV LANG=C.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    CHROME_SANDBOX=False \
    CHROME_BINARY=google-chrome-unstable \
    OUTPUT_DIR=/data

# Run everything from here on out as non-privileged user
USER pptruser
WORKDIR /home/pptruser/app

ENTRYPOINT ["dumb-init", "--"]
CMD ["/bin/archive"]

FROM debian:stretch
LABEL maintainer="Nick Sweeting <bookmark-archiver@sweeting.me>"

RUN apt-get update \
    && apt-get install -qy git wget gnupg2 libgconf-2-4 python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install latest chrome package and fonts to support major charsets (Chinese, Japanese, Arabic, Hebrew, Thai and a few others)
RUN apt-get update && apt-get install -y curl --no-install-recommends \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list' \
    && apt-get update \
    && apt-get install -y chromium fonts-ipafont-gothic fonts-wqy-zenhei fonts-thai-tlwg fonts-kacst ttf-freefont \
      --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /src/*.deb \
    && ln -s /usr/bin/chromium /usr/bin/chromium-browser

# It might be a good idea to use dumb-init to help prevent zombie chrome processes.
# ADD https://github.com/Yelp/dumb-init/releases/download/v1.2.0/dumb-init_1.2.0_amd64 /usr/local/bin/dumb-init
# RUN chmod +x /usr/local/bin/dumb-init

RUN git clone https://github.com/pirate/bookmark-archiver /home/chromeuser/app \
    && pip3 install -r /home/chromeuser/app/archiver/requirements.txt

# Add user so we area strong, independent chrome that don't need --no-sandbox.
RUN groupadd -r chromeuser && useradd -r -g chromeuser -G audio,video chromeuser \
    && mkdir -p /home/chromeuser/app/archiver/output \
    && chown -R chromeuser:chromeuser /home/chromeuser/app/archiver/output \
    && chown -R chromeuser:chromeuser /home/chromeuser

VOLUME /home/chromeuser/app/archiver/output

ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    CHROME_SANDBOX=False \
    OUTPUT_DIR=/home/chromeuser/app/archiver/output

# Run everything from here on out as non-privileged user
USER chromeuser
WORKDIR /home/chromeuser/app

# ENTRYPOINT ["dumb-init", "--"]
# CMD ["/home/chromeuser/app/archive"]

ENTRYPOINT ["python3", "-u", "/home/chromeuser/app/archiver/archive.py"]

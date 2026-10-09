FROM debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
      ca-certificates curl sane-utils sane-airscan python3 python3-img2pdf \
      libusb-0.1-4 libusb-1.0-0 \
    && curl --fail --location --output /tmp/brscan5.deb \
      https://download.brother.com/welcome/dlf104033/brscan5-1.7.0-0.amd64.deb \
    && curl --fail --location --output /tmp/brscan-skey.deb \
      https://download.brother.com/welcome/dlf006652/brscan-skey-0.3.5-0.amd64.deb \
    && echo '9c3a200db3dc7b2b3332dff8c5226b4f3ee560d20b2e1f4918b1faf7124517b2  /tmp/brscan5.deb' | sha256sum --check \
    && echo 'cda25534ea8e3018e7d46b970cb08b36084355adedc933aba0c8c7d03e903db9  /tmp/brscan-skey.deb' | sha256sum --check \
    && apt-get install --no-install-recommends -y /tmp/brscan5.deb /tmp/brscan-skey.deb \
    && rm /tmp/brscan5.deb /tmp/brscan-skey.deb \
    && rm -r /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/scanner-entrypoint
COPY scan.py /usr/local/bin/scan-to-paperless
RUN chmod 755 /usr/local/bin/scanner-entrypoint /usr/local/bin/scan-to-paperless \
    && groupadd --gid 568 paperless \
    && useradd --uid 568 --gid 568 --create-home paperless \
    && chown paperless:paperless \
      /opt/brother/scanner/brscan-skey/brscan-skey.config \
      /etc/opt/brother/scanner/brscan5/brsanenetdevice.cfg

USER 568:568
EXPOSE 54925/udp
ENTRYPOINT ["/usr/local/bin/scanner-entrypoint"]

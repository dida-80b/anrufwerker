FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    asterisk \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /var/lib/asterisk/sounds/custom
COPY etc/ /etc/asterisk/templates/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 5060/udp 8088/tcp 10000-20000/udp
ENTRYPOINT ["/entrypoint.sh"]
CMD ["asterisk", "-f", "-vvv", "-C", "/etc/asterisk/asterisk.conf"]

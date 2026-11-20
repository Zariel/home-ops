FROM docker.io/library/golang:1.26.10 AS go
FROM ghcr.io/actions/actions-runner:2.338.0

LABEL org.opencontainers.image.source="https://github.com/Zariel/home-ops"

USER root

ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        cpio dnsmasq-base docker.io dosfstools erofs-utils fdisk iproute2 iptables \
        kmod libvirt-clients libvirt-daemon-system mtools ovmf \
        qemu-system-x86 qemu-utils rpm squashfs-tools systemd-container \
        util-linux xorriso zstd \
    && rm -rf /var/lib/apt/lists/*

ARG KUBECTL_VERSION=v1.37.1
RUN curl --fail --silent --show-error --location \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
        --output /usr/local/bin/kubectl \
    && curl --fail --silent --show-error --location \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" \
        --output /tmp/kubectl.sha256 \
    && echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum --check \
    && chmod +x /usr/local/bin/kubectl \
    && rm /tmp/kubectl.sha256

COPY --from=go /usr/local/go /usr/local/go
COPY qemu.conf /etc/libvirt/qemu.conf
COPY network.xml /etc/libvirt/qemu/networks/default.xml
COPY entrypoint.sh /usr/local/bin/katl-vmtest-runner
RUN chmod +x /usr/local/bin/katl-vmtest-runner \
    && rm -f /etc/libvirt/qemu/networks/autostart/default.xml

ENV PATH="/usr/local/go/bin:${PATH}" \
    RUNNER_ALLOW_RUNASROOT=1 \
    KATL_CONTAINER_RUNTIME=docker \
    KATL_VMTEST_KVM=on \
    KATL_VMTEST_DEBUG_ON_FAILURE=0 \
    KATL_OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd \
    KATL_OVMF_VARS=/usr/share/OVMF/OVMF_VARS_4M.fd

ENTRYPOINT ["/usr/local/bin/katl-vmtest-runner"]
CMD ["/home/runner/run.sh"]

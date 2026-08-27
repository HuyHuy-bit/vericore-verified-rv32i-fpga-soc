ARG UBUNTU_IMAGE=ubuntu:24.04
ARG UBUNTU_DIGEST=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517
FROM ${UBUNTU_IMAGE}@${UBUNTU_DIGEST} AS toolchain

ARG DEBIAN_FRONTEND=noninteractive
ARG ENV_SCHEMA
ARG VERILATOR_VERSION
ARG VERILATOR_URL
ARG VERILATOR_SHA256
ARG RISCV_TOOLCHAIN_VERSION
ARG RISCV_BINUTILS_VERSION
ARG RISCV_TOOLCHAIN_URL
ARG RISCV_TOOLCHAIN_SHA256
ARG PYTHON_VERSION
ARG VERIFY_IMAGE_REVISION

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf automake bison build-essential ca-certificates curl \
        device-tree-compiler flex git help2man libboost-dev libboost-regex-dev \
        libboost-system-dev libfl-dev libfl2 libgoogle-perftools-dev \
        libjemalloc-dev libtool make perl python3 python3-dev python3-venv \
        util-linux zlib1g-dev \
    && test "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" = "$PYTHON_VERSION" \
    && apt-get clean \
    && find /var/lib/apt/lists -mindepth 1 -delete

RUN curl -fsSL "$VERILATOR_URL" -o /tmp/verilator.tar.gz \
    && printf '%s  %s\n' "$VERILATOR_SHA256" /tmp/verilator.tar.gz | sha256sum -c - \
    && mkdir -p /tmp/verilator-src \
    && tar -xzf /tmp/verilator.tar.gz -C /tmp/verilator-src --strip-components=1 \
    && cd /tmp/verilator-src \
    && autoconf \
    && ./configure --prefix=/opt/rv32i \
    && make -j"$(nproc)" \
    && make install

RUN curl -fsSL "$RISCV_TOOLCHAIN_URL" -o /tmp/riscv-toolchain.tar.gz \
    && printf '%s  %s\n' "$RISCV_TOOLCHAIN_SHA256" /tmp/riscv-toolchain.tar.gz | sha256sum -c - \
    && tar -xzf /tmp/riscv-toolchain.tar.gz -C /opt \
    && test "$(/opt/riscv/bin/riscv64-unknown-elf-gcc -dumpfullversion)" = "${RISCV_TOOLCHAIN_VERSION%%-*}" \
    && test "$(/opt/riscv/bin/riscv64-unknown-elf-as --version | sed -n '1s/.* //p')" = "$RISCV_BINUTILS_VERSION"

RUN mkdir -p /opt/rv32i-cache \
    && printf '{"schema":%s,"image_revision":%s}\n' "$ENV_SCHEMA" "$VERIFY_IMAGE_REVISION" > /opt/rv32i/environment.json

ENV PATH=/opt/rv32i/bin:/opt/riscv/bin:${PATH}
ENV RV32I_ENVIRONMENT_MARKER=/opt/rv32i/environment.json
WORKDIR /work

FROM toolchain AS verify
COPY containers/verify/entrypoint.sh /usr/local/bin/rv32i-entrypoint
RUN chmod 0755 /usr/local/bin/rv32i-entrypoint
ENTRYPOINT ["/usr/local/bin/rv32i-entrypoint"]
CMD ["make", "check"]

FROM verify AS demo
ARG VHS_VERSION
ARG VHS_URL
ARG VHS_SHA256
ARG FFMPEG_VERSION
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && ffmpeg -version | head -n 1 | grep -F "$FFMPEG_VERSION" \
    && curl -fsSL "$VHS_URL" -o /tmp/vhs.deb \
    && printf '%s  %s\n' "$VHS_SHA256" /tmp/vhs.deb | sha256sum -c - \
    && dpkg -i /tmp/vhs.deb \
    && vhs --version | grep -F "$VHS_VERSION" \
    && apt-get clean \
    && find /var/lib/apt/lists -mindepth 1 -delete

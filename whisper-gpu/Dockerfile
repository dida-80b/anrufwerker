FROM ubuntu:24.04 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake build-essential git ca-certificates \
    libvulkan-dev glslc \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/ggerganov/whisper.cpp.git /build

WORKDIR /build
RUN cmake -B build \
    -DGGML_VULKAN=ON \
    -DWHISPER_BUILD_SERVER=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="-Wno-error" \
    && cmake --build build --config Release -j$(nproc) --target whisper-server

# ── Runtime image ──────────────────────────────────────────────────────────
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    libvulkan1 \
    mesa-vulkan-drivers \
    libopenblas0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/build/bin/whisper-server /usr/local/bin/whisper-server
COPY --from=builder /build/build/src/libwhisper.so* /usr/local/lib/
COPY --from=builder /build/build/ggml/src/libggml*.so* /usr/local/lib/
COPY --from=builder /build/build/ggml/src/ggml-vulkan/libggml-vulkan.so* /usr/local/lib/
RUN ldconfig

EXPOSE 8090

CMD ["whisper-server", \
     "-m", "/models/ggml-large-v3-turbo.bin", \
     "-l", "de", \
     "--host", "0.0.0.0", \
     "--port", "8090", \
     "--threads", "4"]

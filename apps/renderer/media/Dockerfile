# apps/renderer/media/Dockerfile
# Build from apps/renderer/: docker build -f media/Dockerfile .

# --- ffmpeg: pinned source, only what the operations use, no network protocols ---
FROM python:3.12.10-slim AS ffmpeg

ARG FFMPEG_VERSION=9.0.2
ARG FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl nasm pkg-config xz-utils libx264-dev libass-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -fsSL -o ffmpeg.tar.xz "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" \
    && echo "${FFMPEG_SHA256}  ffmpeg.tar.xz" | sha256sum -c - \
    && tar -xJf ffmpeg.tar.xz --strip-components=1 \
    && ./configure \
        --prefix=/opt/ffmpeg \
        --disable-everything \
        --disable-network \
        --disable-autodetect \
        --disable-doc \
        --disable-ffplay \
        --disable-debug \
        --enable-gpl \
        --enable-libx264 \
        --enable-libass \
        --enable-protocol=file,pipe \
        --enable-demuxer=mov,matroska \
        --enable-muxer=mp4,mov,ipod,image2,null \
        --enable-decoder=h264,hevc,vp8,vp9,mpeg4,prores,mjpeg,aac,mp3float,opus,vorbis,flac,alac,ac3,eac3,pcm_s16le,pcm_s24le,pcm_f32le \
        --enable-encoder=libx264,aac,mjpeg,wrapped_avframe \
        --enable-parser=h264,hevc,vp8,vp9,aac,opus,vorbis,mpegaudio,ac3,mjpeg \
        --enable-bsf=aac_adtstoasc,h264_mp4toannexb,hevc_mp4toannexb,vp9_superframe \
        --enable-filter=scale,format,fps,select,metadata,null,anull,aresample,aformat,trim,atrim,setpts,asetpts,crop,pad,subtitles,ass,copy,acopy \
    && make -j"$(nproc)" \
    && make install \
    && ! /opt/ffmpeg/bin/ffmpeg -hide_banner -protocols | grep -qE '^\s+(https?|tcp|udp|tls|rtmp|rtp)$'

# --- Runtime: driver plus ffmpeg, non-root, no application secrets ---
FROM python:3.12.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends libx264-164 libass9 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1001 renderer

COPY --from=ffmpeg /opt/ffmpeg /opt/ffmpeg
WORKDIR /app
COPY driver ./driver
COPY media ./media

USER 1001:1001
EXPOSE 8080

# --- Tests: run on Linux in Docker (make media-renderer-check) ---
FROM runtime AS test

USER root
RUN pip install --no-cache-dir pytest==8.4.2
COPY tests ./tests
USER 1001:1001
ENV RENDERER_TEST_CONTAINER=1
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]

# --- Production ---
FROM runtime AS production

CMD ["python", "-m", "media"]

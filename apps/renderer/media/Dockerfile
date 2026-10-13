# apps/renderer/media/Dockerfile
# Build from apps/renderer/: docker build -f media/Dockerfile .

# --- ffmpeg: pinned source, only what the operations use, no network protocols ---
FROM python:3.12.10-slim AS ffmpeg

ARG FFMPEG_VERSION=9.0.2
ARG FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
ARG YUNET_URL=https://github.com/opencv/opencv_zoo/raw/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
ARG YUNET_SHA256=8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl nasm pkg-config xz-utils libx264-dev libass-dev libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# YuNet face detection for automatic framing (MIT licence), pinned by hash.
RUN mkdir -p /opt/yunet \
    && curl -fsSL -o /opt/yunet/face_detection_yunet_2023mar.onnx "${YUNET_URL}" \
    && echo "${YUNET_SHA256}  /opt/yunet/face_detection_yunet_2023mar.onnx" | sha256sum -c -

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
        --enable-libopus \
        --enable-protocol=file,pipe \
        --enable-demuxer=mov,matroska,ogg \
        --enable-muxer=mp4,mov,ipod,ogg,image2,null,rawvideo \
        --enable-decoder=h264,hevc,vp8,vp9,mpeg4,prores,mjpeg,aac,mp3float,opus,vorbis,flac,alac,ac3,eac3,pcm_s16le,pcm_s24le,pcm_f32le \
        --enable-encoder=libx264,libopus,aac,mjpeg,wrapped_avframe,rawvideo \
        --enable-parser=h264,hevc,vp8,vp9,aac,opus,vorbis,mpegaudio,ac3,mjpeg \
        --enable-bsf=aac_adtstoasc,h264_mp4toannexb,hevc_mp4toannexb,vp9_superframe \
        --enable-filter=scale,format,fps,select,metadata,null,anull,aresample,aformat,trim,atrim,setpts,asetpts,crop,pad,subtitles,ass,copy,acopy,silencedetect,ametadata,split,overlay,boxblur,setsar,concat,apad,anullsrc,transpose,hflip,vflip,aselect,asetnsamples \
    && make -j"$(nproc)" \
    && make install \
    && ! /opt/ffmpeg/bin/ffmpeg -hide_banner -protocols | grep -qE '^\s+(https?|tcp|udp|tls|rtmp|rtp)$'

# Caption fonts, each pinned by hash; after the build so a font change keeps its cache.
COPY media/fonts.lock /tmp/fonts.lock
RUN set -eu; mkdir -p /opt/fonts; grep -v '^#' /tmp/fonts.lock | while read -r hash name url; do \
        curl -fsSL -o "/opt/fonts/${name}" "${url}"; \
        echo "${hash}  /opt/fonts/${name}" | sha256sum -c -; \
    done

# --- Runtime: driver, ffmpeg, and OpenCV for face detection; non-root, no application secrets ---
FROM python:3.12.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends libx264-164 libass9 libopus0 fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1001 renderer \
    && pip install --no-cache-dir numpy==2.5.3 opencv-python-headless==4.14.0.94

COPY --from=ffmpeg /opt/ffmpeg /opt/ffmpeg
COPY --from=ffmpeg /opt/yunet /opt/yunet
COPY --from=ffmpeg /opt/fonts /usr/share/fonts/truetype/captions
RUN fc-cache -f
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

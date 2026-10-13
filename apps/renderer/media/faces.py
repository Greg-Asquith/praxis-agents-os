# apps/renderer/media/faces.py

"""Finds faces in raw frames with YuNet and prints them as JSON. Runs as an isolated child.

Usage: python -I faces.py <width> <height> <frames>... where each frames file holds
BGR24 frames of that size. ffmpeg decodes the media, so OpenCV only reads pixels.
Prints one list per file, one list per frame, of [x, y, width, height] faces.
"""

import json
import os
import sys

# numpy's maths library reserves memory per thread, which the child's address-space limit counts.
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import cv2
import numpy as np

MODEL = "/opt/yunet/face_detection_yunet_2023mar.onnx"
SCORE_THRESHOLD = 0.7
NMS_THRESHOLD = 0.3
MAX_FACES = 20


def main() -> None:
    width, height = int(sys.argv[1]), int(sys.argv[2])
    cv2.setNumThreads(2)
    detector = cv2.FaceDetectorYN.create(
        MODEL, "", (width, height), SCORE_THRESHOLD, NMS_THRESHOLD, MAX_FACES
    )
    frame_bytes = width * height * 3
    found = []
    for path in sys.argv[3:]:
        frames = []
        with open(path, "rb") as handle:
            while len(chunk := handle.read(frame_bytes)) == frame_bytes:
                frame = np.frombuffer(chunk, dtype=np.uint8).reshape(height, width, 3)
                _, faces = detector.detect(frame)
                frames.append(
                    []
                    if faces is None
                    else [[round(float(v), 1) for v in face[:4]] for face in faces]
                )
        found.append(frames)
    json.dump(found, sys.stdout)


if __name__ == "__main__":
    main()

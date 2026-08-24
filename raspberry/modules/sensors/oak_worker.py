"""Isolated DepthAI 2.x worker; stdout is a JSON-lines protocol."""

from __future__ import annotations

import argparse
import base64
import json
import time
from typing import Any

import blobconverter
import depthai as dai
import numpy as np

VOC_LABELS = (
    "background",
    "aeroplane",
    "bicycle",
    "bird",
    "boat",
    "bottle",
    "bus",
    "car",
    "cat",
    "chair",
    "cow",
    "diningtable",
    "dog",
    "horse",
    "motorbike",
    "person",
    "pottedplant",
    "sheep",
    "sofa",
    "train",
    "tvmonitor",
)


def emit(kind: str, **payload: Any) -> None:
    try:
        print(json.dumps({"type": kind, **payload}, separators=(",", ":")), flush=True)
    except BrokenPipeError:
        raise SystemExit(0) from None


def depth_zones(depth: np.ndarray, args: argparse.Namespace) -> tuple[dict, dict]:
    height, width = depth.shape
    roi = depth[int(height * args.depth_roi_top) : int(height * args.depth_roi_bottom), :]
    third = width // 3
    areas = {
        "left": roi[:, :third],
        "center": roi[:, third : 2 * third],
        "right": roi[:, 2 * third :],
    }
    zones: dict[str, bool] = {}
    distances: dict[str, float | None] = {}
    for name, area in areas.items():
        valid = area[(area >= 100) & (area <= 8000)]
        if valid.size < args.min_valid_pixels:
            zones[name] = False
            distances[name] = None
            continue
        distance_mm = float(np.percentile(valid, 8))
        zones[name] = distance_mm <= args.obstacle_distance_mm
        distances[name] = round(distance_mm / 10.0, 1)
    return zones, distances


def run(args: argparse.Namespace) -> None:
    model_error = None
    try:
        blob_path = blobconverter.from_zoo(name=args.model, shaves=6)
    except Exception as exc:  # noqa: BLE001
        blob_path = None
        model_error = str(exc)

    pipeline = dai.Pipeline()
    left = pipeline.create(dai.node.MonoCamera)
    right = pipeline.create(dai.node.MonoCamera)
    stereo = pipeline.create(dai.node.StereoDepth)
    depth_output = pipeline.create(dai.node.XLinkOut)
    left.setBoardSocket(dai.CameraBoardSocket.CAM_B)
    right.setBoardSocket(dai.CameraBoardSocket.CAM_C)
    left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    left.setFps(30)
    right.setFps(30)
    stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
    stereo.setLeftRightCheck(True)
    stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
    stereo.setOutputSize(640, 400)
    left.out.link(stereo.left)
    right.out.link(stereo.right)
    depth_output.setStreamName("depth")
    stereo.depth.link(depth_output.input)

    if blob_path:
        color = pipeline.create(dai.node.ColorCamera)
        detector = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
        detection_output = pipeline.create(dai.node.XLinkOut)
        color.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        color.setPreviewSize(300, 300)
        color.setInterleaved(False)
        color.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        color.setFps(30)
        detector.setBlobPath(blob_path)
        detector.setConfidenceThreshold(0.5)
        detector.setBoundingBoxScaleFactor(0.5)
        detector.setDepthLowerThreshold(100)
        detector.setDepthUpperThreshold(8000)
        detector.input.setBlocking(False)
        detection_output.setStreamName("detections")
        color.preview.link(detector.input)
        stereo.depth.link(detector.inputDepth)
        detector.out.link(detection_output.input)

        # Flux JPEG bas-débit pour l'écran de test OAK — même cadrage 300x300
        # que la preview envoyée au détecteur, pour que les boîtes de
        # détection (coordonnées normalisées 0-1) se superposent pile sur
        # l'image affichée. Un .video à un autre ratio décalerait les boîtes.
        color.setVideoSize(300, 300)
        video_encoder = pipeline.create(dai.node.VideoEncoder)
        video_encoder.setDefaultProfilePreset(
            args.video_fps, dai.VideoEncoderProperties.Profile.MJPEG
        )
        video_output = pipeline.create(dai.node.XLinkOut)
        video_output.setStreamName("video")
        color.video.link(video_encoder.input)
        video_encoder.bitstream.link(video_output.input)

    with dai.Device(pipeline) as device:
        depth_queue = device.getOutputQueue("depth", maxSize=2, blocking=False)
        detection_queue = (
            device.getOutputQueue("detections", maxSize=2, blocking=False) if blob_path else None
        )
        video_queue = (
            device.getOutputQueue("video", maxSize=2, blocking=False) if blob_path else None
        )
        emit(
            "ready",
            usb_speed=str(device.getUsbSpeed()).split(".")[-1],
            model=args.model if blob_path else None,
            model_error=model_error,
        )
        last_depth_emit = 0.0
        last_video_emit = 0.0
        interval = 1.0 / max(1, args.fps)
        video_interval = 1.0 / max(1, args.video_fps)
        while True:
            if video_queue:
                packet = video_queue.tryGet()
                now = time.monotonic()
                if packet is not None and now - last_video_emit >= video_interval:
                    jpeg_b64 = base64.b64encode(packet.getData().tobytes()).decode("ascii")
                    emit("video", jpeg_b64=jpeg_b64)
                    last_video_emit = now
            if detection_queue:
                packet = detection_queue.tryGet()
                if packet is not None:
                    items = []
                    for detection in packet.detections:
                        index = int(detection.label)
                        label = VOC_LABELS[index] if 0 <= index < len(VOC_LABELS) else str(index)
                        spatial = detection.spatialCoordinates
                        items.append(
                            {
                                "label": label,
                                "confidence": float(detection.confidence),
                                "cx": float(detection.xmin + detection.xmax) / 2.0,
                                "cy": float(detection.ymin + detection.ymax) / 2.0,
                                "xmin": float(detection.xmin),
                                "xmax": float(detection.xmax),
                                "ymin": float(detection.ymin),
                                "ymax": float(detection.ymax),
                                "x_mm": int(spatial.x),
                                "y_mm": int(spatial.y),
                                "z_mm": int(spatial.z),
                            }
                        )
                    items.sort(key=lambda item: (item["z_mm"] <= 0, item["z_mm"]))
                    emit("detections", items=items)
            packet = depth_queue.tryGet()
            now = time.monotonic()
            if packet is not None and now - last_depth_emit >= interval:
                zones, distances = depth_zones(packet.getFrame(), args)
                emit("depth", zones=zones, distances_cm=distances)
                last_depth_emit = now
            time.sleep(0.01)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="mobilenet-ssd")
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--video-fps", type=int, default=5)
    parser.add_argument("--obstacle-distance-mm", type=int, default=700)
    parser.add_argument("--depth-roi-top", type=float, default=0.45)
    parser.add_argument("--depth-roi-bottom", type=float, default=0.82)
    parser.add_argument("--min-valid-pixels", type=int, default=80)
    args = parser.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        emit("error", message=str(exc))
        raise


if __name__ == "__main__":
    main()

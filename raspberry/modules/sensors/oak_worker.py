"""Isolated DepthAI 2.x worker; stdout is a JSON-lines protocol."""

from __future__ import annotations

import argparse
import base64
import io
import json
import time
from typing import Any

import blobconverter
import depthai as dai
import numpy as np
from oak_depth import depth_zones
from PIL import Image

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
        tracker = pipeline.create(dai.node.ObjectTracker)
        detection_output = pipeline.create(dai.node.XLinkOut)
        tracklet_output = pipeline.create(dai.node.XLinkOut)
        color.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        color.setPreviewSize(300, 300)
        color.setInterleaved(False)
        color.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        # Limiter la source couleur réduit le trafic lorsque l'OAK négocie en
        # USB 2. La preview est partagée par le détecteur et l'écran de test.
        color_fps = max(args.fps, args.video_fps)
        color.setFps(color_fps)
        detector.setBlobPath(blob_path)
        detector.setConfidenceThreshold(0.5)
        detector.setBoundingBoxScaleFactor(0.5)
        detector.setDepthLowerThreshold(100)
        detector.setDepthUpperThreshold(8000)
        detector.input.setBlocking(False)
        detection_output.setStreamName("detections")
        tracklet_output.setStreamName("person_tracklets")
        tracker.setDetectionLabelsToTrack([15])  # classe VOC ``person``
        tracker.setTrackerType(dai.TrackerType.SHORT_TERM_IMAGELESS)
        tracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.UNIQUE_ID)
        color.preview.link(detector.input)
        stereo.depth.link(detector.inputDepth)
        detector.out.link(detection_output.input)
        # Le tracker conserve une identité stable lorsque MobileNet manque une
        # frame. Les détections spatiales lui transmettent aussi X/Y/Z.
        detector.passthrough.link(tracker.inputTrackerFrame)
        detector.passthrough.link(tracker.inputDetectionFrame)
        detector.out.link(tracker.inputDetections)
        tracker.out.link(tracklet_output.input)

        # L'encodeur MJPEG matériel bloque ce modèle OAK-D Lite avec le flux
        # spatial. Envoyer la preview 300x300 brute puis l'encoder sur l'hôte
        # garde le pipeline profondeur/détection vivant et garantit que les
        # boîtes normalisées se superposent exactement à l'image affichée.
        video_output = pipeline.create(dai.node.XLinkOut)
        video_output.setStreamName("video")
        color.preview.link(video_output.input)

    with dai.Device(pipeline) as device:
        depth_queue = device.getOutputQueue("depth", maxSize=2, blocking=False)
        detection_queue = (
            device.getOutputQueue("detections", maxSize=2, blocking=False) if blob_path else None
        )
        tracklet_queue = (
            device.getOutputQueue("person_tracklets", maxSize=4, blocking=False)
            if blob_path
            else None
        )
        video_queue = (
            device.getOutputQueue("video", maxSize=2, blocking=False) if blob_path else None
        )
        emit(
            "ready",
            usb_speed=str(device.getUsbSpeed()).split(".")[-1],
            model=args.model if blob_path else None,
            model_error=model_error,
            person_tracker=bool(blob_path),
        )
        last_depth_emit = 0.0
        last_video_emit = 0.0
        person_rois: list[tuple[float, float, float, float]] = []
        person_rois_ts = 0.0
        interval = 1.0 / max(1, args.fps)
        video_interval = 1.0 / max(1, args.video_fps)
        while True:
            if video_queue:
                packet = video_queue.tryGet()
                now = time.monotonic()
                if packet is not None and now - last_video_emit >= video_interval:
                    frame = packet.getFrame()
                    if frame.ndim == 3 and frame.shape[0] == 3:
                        frame = np.transpose(frame, (1, 2, 0))
                    rgb = np.ascontiguousarray(frame[:, :, ::-1])
                    buffer = io.BytesIO()
                    Image.fromarray(rgb).save(buffer, format="JPEG", quality=72, optimize=False)
                    jpeg_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
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
                    person_rois = [
                        (item["xmin"], item["ymin"], item["xmax"], item["ymax"])
                        for item in items
                        if item["label"] == "person"
                    ]
                    person_rois_ts = time.monotonic()
                    emit("detections", items=items)
            if tracklet_queue:
                packet = tracklet_queue.tryGet()
                if packet is not None:
                    items = []
                    for tracklet in packet.tracklets:
                        roi = tracklet.roi
                        top_left = roi.topLeft()
                        bottom_right = roi.bottomRight()
                        spatial = tracklet.spatialCoordinates
                        status = str(tracklet.status).split(".")[-1]
                        items.append(
                            {
                                "label": "person",
                                "confidence": 1.0,
                                "cx": float(top_left.x + bottom_right.x) / 2.0,
                                "cy": float(top_left.y + bottom_right.y) / 2.0,
                                "xmin": float(top_left.x),
                                "xmax": float(bottom_right.x),
                                "ymin": float(top_left.y),
                                "ymax": float(bottom_right.y),
                                "x_mm": int(spatial.x),
                                "y_mm": int(spatial.y),
                                "z_mm": int(spatial.z),
                                "track_id": int(tracklet.id),
                                "tracking_status": status,
                            }
                        )
                    emit("person_tracklets", items=items)
            packet = depth_queue.tryGet()
            now = time.monotonic()
            if packet is not None and now - last_depth_emit >= interval:
                excluded = person_rois if now - person_rois_ts <= 0.35 else []
                zones, distances = depth_zones(packet.getFrame(), args, excluded)
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

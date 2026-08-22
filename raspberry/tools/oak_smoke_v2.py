"""Minimal DepthAI 2.x stereo test for RVC2/OAK-D Lite."""

import json

import depthai as dai
import numpy as np

pipeline = dai.Pipeline()
left = pipeline.create(dai.node.MonoCamera)
right = pipeline.create(dai.node.MonoCamera)
stereo = pipeline.create(dai.node.StereoDepth)
output = pipeline.create(dai.node.XLinkOut)
left.setBoardSocket(dai.CameraBoardSocket.CAM_B)
right.setBoardSocket(dai.CameraBoardSocket.CAM_C)
left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
left.setFps(30)
right.setFps(30)
stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
stereo.setLeftRightCheck(True)
output.setStreamName("depth")
left.out.link(stereo.left)
right.out.link(stereo.right)
stereo.depth.link(output.input)

with dai.Device(pipeline) as device:
    queue = device.getOutputQueue("depth", maxSize=2, blocking=True)
    frame = None
    for _ in range(12):
        frame = queue.get().getFrame()
    valid = frame[frame > 0]
    print(
        json.dumps(
            {
                "usb": str(device.getUsbSpeed()),
                "shape": list(frame.shape),
                "valid_pct": round(100 * valid.size / frame.size, 1),
                "median_mm": int(np.median(valid)) if valid.size else None,
            }
        ),
        flush=True,
    )

"""Write the rover pose in the map frame for the HTTP API."""

from __future__ import annotations

import json
import math
import os
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener


class PoseWriter(Node):
    def __init__(self) -> None:
        super().__init__("rasprover_pose_writer")
        self._buffer = Buffer()
        self._listener = TransformListener(self._buffer, self)
        self._amcl_quality: tuple[float, float] | None = None
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl_pose, 10)
        self.create_timer(0.2, self._write_pose)

    def _on_amcl_pose(self, message: PoseWithCovarianceStamped) -> None:
        covariance = message.pose.covariance
        position_variance = max(0.0, float(covariance[0]), float(covariance[7]))
        yaw_variance = max(0.0, float(covariance[35]))
        self._amcl_quality = (
            math.sqrt(position_variance),
            math.sqrt(yaw_variance),
        )

    def _write_pose(self) -> None:
        try:
            transform = self._buffer.lookup_transform(
                "map", "base_link", Time(), timeout=Duration(seconds=0.1)
            )
        except TransformException:
            return

        rotation = transform.transform.rotation
        yaw = math.atan2(
            2.0 * (rotation.w * rotation.z + rotation.x * rotation.y),
            1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z),
        )
        payload = {
            "x": transform.transform.translation.x,
            "y": transform.transform.translation.y,
            "yaw": yaw,
            "frame_id": "map",
            "updated_at": time.time(),
        }
        # AMCL publishes this covariance when its estimate changes, not at the
        # pose-writer frequency. Keep the latest known quality while TF proves
        # that the localization pipeline is still alive.
        if self._amcl_quality is not None:
            payload["position_stddev_m"] = self._amcl_quality[0]
            payload["yaw_stddev_rad"] = self._amcl_quality[1]
        temporary_path = "/tmp/current_pose.json.tmp"
        with open(temporary_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, "/tmp/current_pose.json")


def main() -> None:
    rclpy.init()
    node = PoseWriter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

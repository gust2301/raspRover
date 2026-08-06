"""Runs inside the ros2-slam container. Subscribes to /map and writes
the latest OccupancyGrid to /tmp/current_map.json so the API can read
it with a simple 'docker exec cat' instead of fragile ros2 topic echo."""

import json
import os
import time

import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


class MapWriter(Node):
    def __init__(self) -> None:
        super().__init__("map_writer")
        qos = QoSProfile(depth=1)
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        qos.reliability = ReliabilityPolicy.RELIABLE
        self.create_subscription(OccupancyGrid, "/map", self._cb, qos)

    def _cb(self, msg: OccupancyGrid) -> None:
        payload = {
            "updated_at": time.time(),
            "info": {
                "width": msg.info.width,
                "height": msg.info.height,
                "resolution": msg.info.resolution,
                "origin": {
                    "position": {
                        "x": msg.info.origin.position.x,
                        "y": msg.info.origin.position.y,
                    }
                },
            },
            "data": list(msg.data),
        }
        temporary_path = "/tmp/current_map.json.tmp"
        with open(temporary_path, "w") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, "/tmp/current_map.json")


rclpy.init()
rclpy.spin(MapWriter())

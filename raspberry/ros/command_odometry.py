"""Odometrie differentielle ROS 2 estimee depuis les consignes moteurs UDP.

Cette estimation fournit une prediction a slam_toolbox. Le scan matching corrige
ensuite la derive via la transformation map -> odom.
"""

from __future__ import annotations

import json
import math
import socket
import time

import rclpy
from geometry_msgs.msg import Quaternion, TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


def quaternion_from_yaw(yaw: float) -> Quaternion:
    return Quaternion(x=0.0, y=0.0, z=math.sin(yaw / 2.0), w=math.cos(yaw / 2.0))


class CommandOdometry(Node):
    def __init__(self) -> None:
        super().__init__("rasprover_command_odometry")
        self.declare_parameter("udp_port", 7667)
        self.declare_parameter("max_linear_speed_m_s", 0.65)
        self.declare_parameter("wheel_separation_m", 0.18)
        self.declare_parameter("command_timeout_s", 0.5)
        self.declare_parameter("laser_x_m", 0.0)
        self.declare_parameter("laser_y_m", 0.0)
        self.declare_parameter("laser_yaw_deg", 140.0)

        port = int(self.get_parameter("udp_port").value)
        self._max_speed = float(self.get_parameter("max_linear_speed_m_s").value)
        self._wheel_separation = float(self.get_parameter("wheel_separation_m").value)
        self._timeout = float(self.get_parameter("command_timeout_s").value)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("127.0.0.1", port))
        self._socket.setblocking(False)

        self._left = self._right = 0.0
        self._x = self._y = self._yaw = 0.0
        self._last_command = 0.0
        self._last_update = time.monotonic()
        self._odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self._tf = TransformBroadcaster(self)
        self._static_tf = StaticTransformBroadcaster(self)
        self._publish_laser_transform()
        self.create_timer(0.05, self._tick)
        self.get_logger().info(f"Odometrie commandes en ecoute sur UDP 127.0.0.1:{port}")

    def _publish_laser_transform(self) -> None:
        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = "base_link"
        transform.child_frame_id = "laser"
        transform.transform.translation.x = float(self.get_parameter("laser_x_m").value)
        transform.transform.translation.y = float(self.get_parameter("laser_y_m").value)
        transform.transform.rotation = quaternion_from_yaw(
            math.radians(float(self.get_parameter("laser_yaw_deg").value))
        )
        self._static_tf.sendTransform(transform)

    def _receive_latest(self) -> None:
        while True:
            try:
                raw, _ = self._socket.recvfrom(2048)
            except BlockingIOError:
                return
            try:
                command = json.loads(raw)
                self._left = max(-1.0, min(1.0, float(command["left"])))
                self._right = max(-1.0, min(1.0, float(command["right"])))
                self._last_command = time.monotonic()
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.get_logger().warning("Commande odometrie UDP invalide")

    def _tick(self) -> None:
        self._receive_latest()
        now = time.monotonic()
        dt = min(0.2, now - self._last_update)
        self._last_update = now
        if now - self._last_command > self._timeout:
            self._left = self._right = 0.0

        velocity_left = self._left * self._max_speed
        velocity_right = self._right * self._max_speed
        linear = (velocity_left + velocity_right) / 2.0
        angular = (velocity_right - velocity_left) / self._wheel_separation
        self._yaw = math.atan2(math.sin(self._yaw + angular * dt), math.cos(self._yaw + angular * dt))
        self._x += linear * math.cos(self._yaw) * dt
        self._y += linear * math.sin(self._yaw) * dt

        stamp = self.get_clock().now().to_msg()
        rotation = quaternion_from_yaw(self._yaw)
        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_link"
        transform.transform.translation.x = self._x
        transform.transform.translation.y = self._y
        transform.transform.rotation = rotation
        self._tf.sendTransform(transform)

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = self._x
        odom.pose.pose.position.y = self._y
        odom.pose.pose.orientation = rotation
        odom.twist.twist.linear.x = linear
        odom.twist.twist.angular.z = angular
        odom.pose.covariance[0] = odom.pose.covariance[7] = 0.05
        odom.pose.covariance[35] = 0.1
        self._odom_pub.publish(odom)

    def destroy_node(self) -> bool:
        self._socket.close()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = CommandOdometry()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

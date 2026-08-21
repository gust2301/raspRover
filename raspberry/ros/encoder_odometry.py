"""Odometrie ROS 2 fondee sur les encodeurs reels du chassis Waveshare."""

from __future__ import annotations

import json
import math
import pathlib
import socket
import time

import rclpy
from encoder_kinematics import EncoderIntegrator, WheelSample
from geometry_msgs.msg import Quaternion, TransformStamped
from laser_scan_matching import match_scans, scan_points
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


def quaternion_from_yaw(yaw: float) -> Quaternion:
    return Quaternion(x=0.0, y=0.0, z=math.sin(yaw / 2.0), w=math.cos(yaw / 2.0))


class EncoderOdometry(Node):
    def __init__(self) -> None:
        super().__init__("rasprover_encoder_odometry")
        self.declare_parameter("udp_port", 7667)
        self.declare_parameter("wheel_separation_m", 0.33)
        self.declare_parameter("counterclockwise_wheel_separation_m", 0.26)
        self.declare_parameter("clockwise_wheel_separation_m", 0.44)
        self.declare_parameter("left_encoder_sign", 1.0)
        self.declare_parameter("right_encoder_sign", 1.0)
        self.declare_parameter("feedback_timeout_s", 0.6)
        self.declare_parameter("laser_x_m", 0.0)
        self.declare_parameter("laser_y_m", 0.0)
        self.declare_parameter("laser_z_m", 0.30)
        self.declare_parameter("laser_yaw_deg", 140.0)

        port = int(self.get_parameter("udp_port").value)
        self._timeout = float(self.get_parameter("feedback_timeout_s").value)
        self._integrator = EncoderIntegrator(
            float(self.get_parameter("wheel_separation_m").value),
            float(self.get_parameter("left_encoder_sign").value),
            float(self.get_parameter("right_encoder_sign").value),
            float(self.get_parameter("counterclockwise_wheel_separation_m").value),
            float(self.get_parameter("clockwise_wheel_separation_m").value),
        )
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("127.0.0.1", port))
        self._socket.setblocking(False)
        self._last_feedback = 0.0
        self._last_sequence = 0
        self._last_scan_points = None
        self._last_scan_pose: tuple[float, float, float] | None = None
        self._last_scan_at = 0.0
        self._scan_match_residual_m: float | None = None
        self._heading_source = "encoders"
        self._status_path = pathlib.Path("/tmp/encoder_odometry_status.json")
        self._odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self._tf = TransformBroadcaster(self)
        self._static_tf = StaticTransformBroadcaster(self)
        self._publish_laser_transform()
        self.create_subscription(LaserScan, "/scan", self._on_scan, qos_profile_sensor_data)
        self.create_timer(0.02, self._tick)
        self.get_logger().info(f"Odometrie encodeurs en ecoute sur UDP 127.0.0.1:{port}")

    def _publish_laser_transform(self) -> None:
        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = "base_link"
        transform.child_frame_id = "laser"
        transform.transform.translation.x = float(self.get_parameter("laser_x_m").value)
        transform.transform.translation.y = float(self.get_parameter("laser_y_m").value)
        transform.transform.translation.z = float(self.get_parameter("laser_z_m").value)
        transform.transform.rotation = quaternion_from_yaw(
            math.radians(float(self.get_parameter("laser_yaw_deg").value))
        )
        self._static_tf.sendTransform(transform)

    @staticmethod
    def _decode(raw: bytes) -> WheelSample:
        value = json.loads(raw)
        return WheelSample(
            left_speed_m_s=float(value["left_speed_m_s"]),
            right_speed_m_s=float(value["right_speed_m_s"]),
            left_distance_m=float(value["left_distance_cm"]) / 100.0,
            right_distance_m=float(value["right_distance_cm"]) / 100.0,
            timestamp=float(value["timestamp"]),
            sequence=int(value["sequence"]),
        )

    def _receive_latest(self) -> WheelSample | None:
        latest = None
        while True:
            try:
                raw, _ = self._socket.recvfrom(4096)
            except BlockingIOError:
                return latest
            try:
                candidate = self._decode(raw)
                if all(
                    math.isfinite(value)
                    for value in (
                        candidate.left_speed_m_s,
                        candidate.right_speed_m_s,
                        candidate.left_distance_m,
                        candidate.right_distance_m,
                        candidate.timestamp,
                    )
                ):
                    latest = candidate
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self.get_logger().warning("Trame encodeur UDP invalide")

    def _tick(self) -> None:
        sample = self._receive_latest()
        if sample is not None:
            self._last_feedback = time.monotonic()
            self._last_sequence = sample.sequence
            self._integrator.update(sample)
        age = time.monotonic() - self._last_feedback if self._last_feedback else math.inf
        ready = age <= self._timeout
        self._publish_odometry(ready)
        self._write_status(ready, age)

    @staticmethod
    def _normalized(angle: float) -> float:
        return math.atan2(math.sin(angle), math.cos(angle))

    def _on_scan(self, message: LaserScan) -> None:
        points = scan_points(
            message.ranges,
            float(message.angle_min),
            float(message.angle_increment),
            max(0.15, float(message.range_min)),
            min(6.0, float(message.range_max)),
        )
        now = time.monotonic()
        pose = (self._integrator.x, self._integrator.y, self._integrator.yaw)
        if self._last_scan_points is None or self._last_scan_pose is None:
            self._last_scan_points = points
            self._last_scan_pose = pose
            self._last_scan_at = now
            return

        previous_x, previous_y, previous_yaw = self._last_scan_pose
        delta_x = pose[0] - previous_x
        delta_y = pose[1] - previous_y
        cosine = math.cos(previous_yaw)
        sine = math.sin(previous_yaw)
        initial_translation = (
            cosine * delta_x + sine * delta_y,
            -sine * delta_x + cosine * delta_y,
        )
        initial_yaw = self._normalized(pose[2] - previous_yaw)
        travelled = math.hypot(*initial_translation)
        # Ne jamais intégrer le bruit de scans successifs lorsque le rover est
        # immobile. Une base géométrique minimale rend aussi l'ICP plus stable.
        if travelled < 0.03 and abs(initial_yaw) < math.radians(3.0):
            return
        matched = match_scans(
            self._last_scan_points,
            points,
            initial_yaw,
            initial_translation,
        )
        if matched is not None:
            correction = self._normalized(matched.yaw - initial_yaw)
            if matched.residual_m <= 0.12 and abs(correction) <= math.radians(25.0):
                self._integrator.yaw = self._normalized(previous_yaw + matched.yaw)
                pose = (self._integrator.x, self._integrator.y, self._integrator.yaw)
                self._scan_match_residual_m = matched.residual_m
                self._heading_source = "lidar"
                self._last_scan_points = points
                self._last_scan_pose = pose
                self._last_scan_at = now
                return
            else:
                self._heading_source = "encoders"
        elif now - self._last_scan_at > 1.0:
            self._heading_source = "encoders"
        if now - self._last_scan_at > 1.0:
            self._last_scan_points = points
            self._last_scan_pose = pose
            self._last_scan_at = now

    def _publish_odometry(self, ready: bool) -> None:
        stamp = self.get_clock().now().to_msg()
        rotation = quaternion_from_yaw(self._integrator.yaw)
        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_link"
        transform.transform.translation.x = self._integrator.x
        transform.transform.translation.y = self._integrator.y
        transform.transform.rotation = rotation
        self._tf.sendTransform(transform)

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = self._integrator.x
        odom.pose.pose.position.y = self._integrator.y
        odom.pose.pose.orientation = rotation
        if ready:
            odom.twist.twist.linear.x = self._integrator.linear
            odom.twist.twist.angular.z = self._integrator.angular
            odom.pose.covariance[0] = odom.pose.covariance[7] = 0.0025
            odom.pose.covariance[35] = 0.01
        else:
            odom.pose.covariance[0] = odom.pose.covariance[7] = 1000.0
            odom.pose.covariance[35] = 1000.0
        self._odom_pub.publish(odom)

    def _write_status(self, ready: bool, age: float) -> None:
        value = {
            "ready": ready,
            "feedback_age_s": None if not math.isfinite(age) else round(age, 3),
            "sequence": self._last_sequence,
            "x": self._integrator.x,
            "y": self._integrator.y,
            "yaw": self._integrator.yaw,
            "linear_m_s": self._integrator.linear if ready else 0.0,
            "angular_rad_s": self._integrator.angular if ready else 0.0,
            "heading_source": self._heading_source,
            "scan_match_residual_m": self._scan_match_residual_m,
            "updated_at": time.time(),
        }
        temporary = self._status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, separators=(",", ":")))
        temporary.replace(self._status_path)

    def destroy_node(self) -> bool:
        self._socket.close()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = EncoderOdometry()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

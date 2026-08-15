"""Bridge Nav2 velocity commands and waypoint requests to the rover API."""

from __future__ import annotations

import json
import math
import os
import socket
import time

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import FollowWaypoints
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


class Nav2Bridge(Node):
    def __init__(self) -> None:
        super().__init__("rasprover_nav2_bridge")
        self.declare_parameter("motor_udp_port", 7668)
        self.declare_parameter("command_udp_port", 7669)
        self.declare_parameter("max_linear_speed_m_s", 0.65)
        self.declare_parameter("wheel_separation_m", 0.18)
        self.declare_parameter("initial_pose_x", 0.0)
        self.declare_parameter("initial_pose_y", 0.0)
        self.declare_parameter("initial_pose_yaw", 0.0)

        self._motor_port = int(self.get_parameter("motor_udp_port").value)
        self._max_speed = float(self.get_parameter("max_linear_speed_m_s").value)
        self._wheel_separation = float(self.get_parameter("wheel_separation_m").value)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._command_socket.bind(("127.0.0.1", int(self.get_parameter("command_udp_port").value)))
        self._command_socket.setblocking(False)
        self._client = ActionClient(self, FollowWaypoints, "/follow_waypoints")
        initial_pose_qos = QoSProfile(depth=1)
        initial_pose_qos.reliability = ReliabilityPolicy.RELIABLE
        initial_pose_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", initial_pose_qos
        )
        self._goal_handle = None
        self._initial_pose: dict[str, float] | None = None
        self._initial_pose_repeats = 0
        self._amcl_state_client = self.create_client(GetState, "/amcl/get_state")
        self._amcl_state_future = None
        self._status = {"state": "idle", "current_waypoint": None, "updated_at": time.time()}

        self.create_subscription(Twist, "/cmd_vel", self._on_velocity, 10)
        self.create_timer(0.1, self._receive_commands)
        self.create_timer(0.5, self._write_status)
        self.create_timer(0.1, self._publish_initial_pose_when_ready)
        self._set_initial_pose(
            {
                "x": float(self.get_parameter("initial_pose_x").value),
                "y": float(self.get_parameter("initial_pose_y").value),
                "yaw": float(self.get_parameter("initial_pose_yaw").value),
            }
        )

    def _on_velocity(self, message: Twist) -> None:
        half_track = self._wheel_separation / 2.0
        left_m_s = message.linear.x - message.angular.z * half_track
        right_m_s = message.linear.x + message.angular.z * half_track
        scale = max(self._max_speed, abs(left_m_s), abs(right_m_s))
        payload = json.dumps({"left": left_m_s / scale, "right": right_m_s / scale}).encode()
        self._socket.sendto(payload, ("127.0.0.1", self._motor_port))

    def _receive_commands(self) -> None:
        while True:
            try:
                raw, _ = self._command_socket.recvfrom(65535)
            except BlockingIOError:
                return
            try:
                command = json.loads(raw)
                action = command.get("action")
                if action == "follow_waypoints":
                    self._follow(command.get("waypoints", []))
                elif action == "set_initial_pose":
                    self._set_initial_pose(command.get("pose", {}))
                elif action == "cancel":
                    self._cancel()
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self.get_logger().warning(f"Commande Nav2 invalide: {exc}")

    def _set_initial_pose(self, value: dict) -> None:
        self._initial_pose = {
            "x": float(value.get("x", 0.0)),
            "y": float(value.get("y", 0.0)),
            "yaw": float(value.get("yaw", 0.0)),
        }
        self._initial_pose_repeats = 300

    def _publish_initial_pose_when_ready(self) -> None:
        if self._initial_pose_repeats <= 0:
            return
        if self._initial_pose_pub.get_subscription_count() <= 0:
            return
        if not self._amcl_state_client.service_is_ready():
            return
        if self._amcl_state_future is None:
            self._amcl_state_future = self._amcl_state_client.call_async(GetState.Request())
            return
        if not self._amcl_state_future.done():
            return
        response = self._amcl_state_future.result()
        self._amcl_state_future = None
        if response is None or response.current_state.id != State.PRIMARY_STATE_ACTIVE:
            return
        self._publish_initial_pose()
        self._initial_pose_repeats = 0
        if self._initial_pose is not None:
            self.get_logger().info(
                "Pose initiale publiée: "
                f"x={self._initial_pose['x']:.2f}, y={self._initial_pose['y']:.2f}, "
                f"yaw={self._initial_pose['yaw']:.2f}"
            )

    def _publish_initial_pose(self) -> None:
        if self._initial_pose is None:
            return
        x = self._initial_pose["x"]
        y = self._initial_pose["y"]
        yaw = self._initial_pose["yaw"]
        message = PoseWithCovarianceStamped()
        message.header.frame_id = "map"
        # Un timestamp nul demande à TF la dernière transformation disponible
        # et évite une extrapolation de quelques millisecondes vers le futur.
        message.pose.pose.position.x = x
        message.pose.pose.position.y = y
        message.pose.pose.orientation.z = math.sin(yaw / 2.0)
        message.pose.pose.orientation.w = math.cos(yaw / 2.0)
        message.pose.covariance[0] = 0.25
        message.pose.covariance[7] = 0.25
        message.pose.covariance[35] = 0.068
        self._initial_pose_pub.publish(message)

    def _follow(self, waypoints: list[dict]) -> None:
        if not waypoints:
            self._set_status("error", error="Aucun point de passage")
            return
        if not self._client.wait_for_server(timeout_sec=2.0):
            self._set_status("error", error="Action FollowWaypoints indisponible")
            return

        goal = FollowWaypoints.Goal()
        for waypoint in waypoints:
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.header.stamp = self.get_clock().now().to_msg()
            pose.pose.position.x = float(waypoint["x"])
            pose.pose.position.y = float(waypoint["y"])
            yaw = float(waypoint.get("yaw", 0.0))
            pose.pose.orientation.z = math.sin(yaw / 2.0)
            pose.pose.orientation.w = math.cos(yaw / 2.0)
            goal.poses.append(pose)

        self._set_status("starting", waypoint_count=len(goal.poses), current_waypoint=0)
        future = self._client.send_goal_async(goal, feedback_callback=self._feedback)
        future.add_done_callback(self._goal_response)

    def _goal_response(self, future) -> None:
        self._goal_handle = future.result()
        if not self._goal_handle.accepted:
            self._set_status("error", error="Patrouille refusée par Nav2")
            self._goal_handle = None
            self._send_stop(mission_finished=True)
            return
        self._set_status("running")
        result = self._goal_handle.get_result_async()
        result.add_done_callback(self._result)

    def _feedback(self, feedback) -> None:
        self._set_status("running", current_waypoint=int(feedback.feedback.current_waypoint))

    def _result(self, future) -> None:
        wrapped_result = future.result()
        status = wrapped_result.status
        missed = getattr(wrapped_result.result, "missed_waypoints", [])
        missed_indexes = [int(item.index) for item in missed]
        succeeded = status == GoalStatus.STATUS_SUCCEEDED and not missed_indexes
        state = "completed" if succeeded else "error"
        self._set_status(
            state,
            result_status=int(status),
            missed_waypoints=missed_indexes,
            error=None if succeeded else "Un ou plusieurs points sont inaccessibles",
        )
        self._goal_handle = None
        self._send_stop(mission_finished=True)

    def _cancel(self) -> None:
        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()
        self._goal_handle = None
        self._set_status("cancelled")
        self._send_stop()

    def _send_stop(self, *, mission_finished: bool = False) -> None:
        payload = json.dumps(
            {"left": 0.0, "right": 0.0, "mission_finished": mission_finished}
        ).encode()
        self._socket.sendto(payload, ("127.0.0.1", self._motor_port))

    def _set_status(self, state: str, **extra) -> None:
        self._status.update(extra)
        self._status["state"] = state
        self._status["updated_at"] = time.time()

    def _write_status(self) -> None:
        self._status["action_server_ready"] = self._client.server_is_ready()
        # ``updated_at`` dates the last mission state transition. Keep a
        # separate heartbeat for API health checks so an idle, healthy bridge
        # does not look stale after two seconds.
        self._status["heartbeat_at"] = time.time()
        temporary_path = "/tmp/nav2_status.json.tmp"
        with open(temporary_path, "w", encoding="utf-8") as stream:
            json.dump(self._status, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, "/tmp/nav2_status.json")

    def destroy_node(self) -> bool:
        self._send_stop()
        self._socket.close()
        self._command_socket.close()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = Nav2Bridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

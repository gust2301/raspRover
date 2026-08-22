#!/usr/bin/env python3
"""Validate a taught route with Nav2 without sending motor commands."""

from __future__ import annotations

import json
import math
import sys

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose
from rclpy.action import ActionClient
from rclpy.node import Node


class RouteValidator(Node):
    def __init__(self) -> None:
        super().__init__("rasprover_route_validator")
        self._client = ActionClient(self, ComputePathToPose, "/compute_path_to_pose")

    @staticmethod
    def _pose(values: dict) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = "map"
        yaw = float(values.get("yaw", 0.0))
        pose.pose.position.x = float(values["x"])
        pose.pose.position.y = float(values["y"])
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def validate(self, poses: list[dict], labels: list[str]) -> dict:
        if len(poses) < 2:
            return {"ok": False, "error": "Aucun point à valider", "failed_point": None}
        if len(labels) != len(poses):
            return {"ok": False, "error": "Libellés de trajet invalides", "failed_point": None}
        if not self._client.wait_for_server(timeout_sec=5.0):
            return {"ok": False, "error": "Planificateur Nav2 indisponible", "failed_point": None}

        for segment, (start, goal) in enumerate(zip(poses, poses[1:], strict=False)):
            if math.hypot(
                float(goal["x"]) - float(start["x"]),
                float(goal["y"]) - float(start["y"]),
            ) < 0.05:
                # Plusieurs vues caméra peuvent légitimement partager la même
                # position et ne nécessitent aucun calcul de trajet.
                continue
            request = ComputePathToPose.Goal()
            request.start = self._pose(start)
            request.goal = self._pose(goal)
            request.use_start = True
            request.planner_id = "GridBased"
            future = self._client.send_goal_async(request)
            rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
            if not future.done() or future.result() is None or not future.result().accepted:
                return {
                    "ok": False,
                    "error": f"Nav2 n'a pas accepté la liaison vers « {labels[segment + 1]} »",
                    "failed_point": segment,
                }
            result_future = future.result().get_result_async()
            rclpy.spin_until_future_complete(self, result_future, timeout_sec=12.0)
            if not result_future.done() or result_future.result() is None:
                return {
                    "ok": False,
                    "error": f"Validation Nav2 trop longue vers « {labels[segment + 1]} »",
                    "failed_point": segment,
                }
            wrapped = result_future.result()
            result = wrapped.result
            succeeded = (
                wrapped.status == GoalStatus.STATUS_SUCCEEDED
                and int(result.error_code) == 0
            )
            if not succeeded:
                detail = str(getattr(result, "error_msg", "")).strip()
                message = (
                    f"« {labels[segment + 1]} » inaccessible depuis "
                    f"« {labels[segment]} »"
                )
                if detail:
                    message = f"{message} : {detail}"
                return {
                    "ok": False,
                    "error": message,
                    "failed_point": segment,
                    "error_code": int(result.error_code),
                }
        return {"ok": True, "validated_points": len(poses) - 1}


def main() -> None:
    try:
        payload = json.loads(sys.argv[1])
        poses = payload["poses"]
        labels = payload["labels"]
        if not isinstance(poses, list):
            raise ValueError("poses invalides")
        rclpy.init()
        node = RouteValidator()
        try:
            result = node.validate(poses, labels)
        finally:
            node.destroy_node()
            rclpy.shutdown()
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"Validation Nav2 impossible : {exc}"}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

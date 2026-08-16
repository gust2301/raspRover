from pathlib import Path


def test_deploy_restarts_lidar_before_control_api():
    script = (Path(__file__).parents[1] / "scripts" / "deploy.sh").read_text()

    lidar_restart = script.index("sudo systemctl restart ros2-lidar.service")
    lidar_wait = script.index("Attente du nouveau conteneur ros2-lidar")
    api_restart = script.index("sudo systemctl restart rasprover-control.service")

    assert lidar_restart < lidar_wait < api_restart
    assert "docker inspect -f '{{.State.Running}}' ros2-lidar" in script
    assert "modules/control/encoder_kinematics" in script

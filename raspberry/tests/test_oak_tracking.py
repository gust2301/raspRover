from modules.sensors.oak_d_lite import OakDLiteSensor


def _track(track_id: int, z_mm: int, status: str = "TRACKED") -> dict:
    return {
        "label": "person",
        "confidence": 1.0,
        "cx": 0.5,
        "cy": 0.6,
        "x_mm": 0,
        "y_mm": 0,
        "z_mm": z_mm,
        "track_id": track_id,
        "tracking_status": status,
    }


def test_oak_keeps_the_same_person_track_instead_of_switching_to_nearest():
    oak = OakDLiteSensor()
    oak._handle_message({"type": "ready", "usb_speed": "SUPER", "person_tracker": True})
    oak._handle_message({"type": "person_tracklets", "items": [_track(7, 1500)]})
    oak._handle_message(
        {
            "type": "person_tracklets",
            "items": [_track(7, 1700), _track(9, 800)],
        }
    )

    assert oak.person_target is not None
    assert oak.person_target.track_id == 7


def test_raw_detections_do_not_replace_a_tracked_person():
    oak = OakDLiteSensor()
    oak._handle_message({"type": "ready", "usb_speed": "SUPER", "person_tracker": True})
    oak._handle_message({"type": "person_tracklets", "items": [_track(7, 1500)]})
    oak._handle_message(
        {
            "type": "detections",
            "items": [
                {
                    "label": "person",
                    "confidence": 0.9,
                    "cx": 0.2,
                    "cy": 0.5,
                    "x_mm": -900,
                    "y_mm": 0,
                    "z_mm": 700,
                }
            ],
        }
    )

    assert oak.person_target is not None
    assert oak.person_target.track_id == 7

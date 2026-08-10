from modules.api.db import get_map_home, init_db, set_map_home


def test_map_home_is_persisted_and_can_be_redefined(tmp_path):
    init_db(tmp_path / "rasprover.db")

    first = set_map_home("entrepot", 1.0, 2.0, 0.5)
    assert get_map_home("entrepot") == first

    replacement = set_map_home("entrepot", -1.0, 3.0, -0.25)
    assert get_map_home("entrepot") == replacement
    assert get_map_home("autre-carte") is None

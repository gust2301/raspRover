from modules.map_names import normalize_map_name, validate_map_name


def test_normalize_map_name_accepts_human_labels():
    assert normalize_map_name("Entrepôt principal") == "entrepot-principal"
    assert normalize_map_name("  Carte étage 2.yaml  ") == "carte-etage-2"


def test_normalize_map_name_rejects_empty_labels():
    assert normalize_map_name("   ") is None
    assert normalize_map_name("🚗") is None


def test_validate_map_name_accepts_storage_names_and_extensions():
    assert validate_map_name("entrepot-principal") == "entrepot-principal"
    assert validate_map_name("entrepot-principal.yaml") == "entrepot-principal"


def test_validate_map_name_rejects_paths_and_human_labels():
    assert validate_map_name("/tmp/map") is None
    assert validate_map_name("carte principale") is None

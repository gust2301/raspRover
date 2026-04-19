"""Exceptions spécifiques au module Contrôle."""


class ControlError(Exception):
    """Erreur générique du module Contrôle."""


class LinkNotOpenError(ControlError):
    """Levée quand on tente d'utiliser l'ESP32Link sans l'avoir ouvert."""


class InvalidParameterError(ControlError):
    """Paramètre hors plage (vitesse, angle, etc.)."""


class ESP32TimeoutError(ControlError):
    """Pas de réponse de l'ESP32 dans le délai imparti."""

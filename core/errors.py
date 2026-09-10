class AstraError(Exception):
    """Base exception for all Astra errors."""
    pass

class CommandError(AstraError):
    """Raised when a command fails gracefully and should be reported to the HUD."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

class ConfigurationError(AstraError):
    """Raised when critical configuration is missing."""
    pass

from enum import Enum

class PluginCategory(Enum):
    SYSTEM = "system"
    MEDIA = "media"
    SECURITY = "security"
    NETWORK_OSINT = "network_osint"
    AI = "ai"

MAX_MESSAGE_LENGTH = 4096

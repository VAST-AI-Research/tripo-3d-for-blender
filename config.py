import bpy
import os
import logging
from functools import lru_cache

logger = None
def get_logger():
    global logger
    if logger is not None:
        return logger
    logger = logging.getLogger("tripo_addon")
    logger.setLevel(logging.INFO)

    # Get the addon's directory path
    addon_dir = os.path.dirname(os.path.realpath(__file__))
    log_file = os.path.join(addon_dir, "tripo_addon.log")

    try:
        # File handler
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

    except PermissionError:
        # If we can't create a log file, just use console logging
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        print("Warning: Could not create log file. Logging to console only.")
    return logger


class TripoConfig:
    API_BASE_URL = "https://api.tripo3d.ai/v2/openapi"
    TASK_ENDPOINT = f"{API_BASE_URL}/task"
    BALANCE_ENDPOINT = f"{API_BASE_URL}/user/balance"
    UPLOAD_ENDPOINT = f"{API_BASE_URL}/upload"
    MODEL_ENDPOINT = f"{API_BASE_URL}/model"  # Added for model-related operations

    # Task types according to documentation
    TASK_TYPES = {
        "TEXT_TO_MODEL": "text_to_model",
        "IMAGE_TO_MODEL": "image_to_model",
        "MULTIVIEW_TO_MODEL": "multiview_to_model",
        "ANIMATION": "animation",  # Added animation task type
        "POST_PROCESS": "post_process",  # Added post-process task type
    }

    # Model versions
    MODEL_VERSIONS = {"V1": "v1.0", "V2": "v2.0-20240919"}

    # Model styles
    MODEL_STYLES = {
        "ORIGINAL": "original",
        "CARTOON": "cartoon",
        "REALISTIC": "realistic",
    }

    # Animation types
    ANIMATION_TYPES = {"WALK": "walk", "RUN": "run", "IDLE": "idle", "DANCE": "dance"}

    # Status codes
    STATUS_CODES = {
        "QUEUED": "queued",
        "RUNNING": "running",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "SUCCESS": "success",  # Add success status
    }

    DEFAULT_TIMEOUT = 30  # seconds
    MAX_RETRIES = 3
    POLLING_INTERVAL = 2  # seconds

    # Add supported file types
    SUPPORTED_FILE_TYPES = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes

    @classmethod
    def get_task_url(cls, task_id=None):
        if task_id:
            return f"{cls.TASK_ENDPOINT}/{task_id}"
        return cls.TASK_ENDPOINT

    @classmethod
    def get_balance_url(cls):
        return cls.BALANCE_ENDPOINT


class TripoSettings(bpy.types.PropertyGroup):
    api_key: bpy.props.StringProperty(
        name="API Key",
        description="API Key for Tripo 3D",
        default="",
        subtype="PASSWORD",
    )
    api_key_confirmed: bpy.props.BoolProperty(name="API Key Confirmed", default=False)
    user_balance: bpy.props.StringProperty(name="User Balance", default="----")

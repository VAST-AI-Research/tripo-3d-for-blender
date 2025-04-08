import os
import tempfile
import requests
from functools import wraps
import time
import bpy
from . import config

def retry_with_backoff(func):
    """
    Decorator function that retries API calls when they fail, using an exponential backoff strategy

    Args:
        func: The function to decorate

    Returns:
        Wrapped function that will automatically retry on API call failures
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = config.TripoConfig.MAX_RETRIES
        retry_delay = 1  # Initial delay of 1 second

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:  # Last attempt
                    raise  # Re-raise the last error

                config.logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

    return wrapper


@retry_with_backoff
def fetch_data(url, headers_tuple, method="GET", data=None, files=None):
    """
    General function for retrieving data from API

    Args:
        url: API endpoint URL
        headers_tuple: Request headers in format ("Key1", "Value1", "Key2", "Value2", ...)
        method: HTTP method (GET/POST)
        data: POST request data
        files: File upload data

    Returns:
        Parsed JSON response
    """
    headers = dict([headers_tuple[i:i+2] for i in range(0, len(headers_tuple), 2)])
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            if files:
                response = requests.post(url, headers=headers, files=files)
            elif data:
                response = requests.post(url, headers=headers, json=data)
            else:
                response = requests.post(url, headers=headers)

        if response.status_code == 200:
            return response.json()
        else:
            config.logger.error(f"Failed to get data: {response.status_code}")
            raise Exception(f"API error: Received response code {response.status_code}")
    except requests.RequestException as e:
        config.logger.error(f"Network error: {str(e)}")
        raise


def upload_file(url, headers_tuple, file_path):
    """
    Upload a file to Tripo API

    Args:
        url: Upload endpoint URL
        headers_tuple: Authorization headers
        file_path: Path to the file to upload

    Returns:
        dict: API response containing file_token
    """
    headers = dict([headers_tuple[i:i+2] for i in range(0, len(headers_tuple), 2)])

    # Verify file existence
    if not os.path.exists(file_path):
        raise ValueError(f"File not found: {file_path}")

    # Verify file size
    file_size = os.path.getsize(file_path)
    if file_size > config.TripoConfig.MAX_FILE_SIZE:
        raise ValueError(
            f"File size ({file_size} bytes) exceeds maximum allowed size ({config.TripoConfig.MAX_FILE_SIZE} bytes)"
        )

    # Get file extension and validate type
    file_ext = os.path.splitext(file_path)[1][1:].lower()
    if file_ext not in config.TripoConfig.SUPPORTED_FILE_TYPES:
        raise ValueError(
            f"Unsupported file type: {file_ext}. Supported types: {', '.join(config.TripoConfig.SUPPORTED_FILE_TYPES.keys())}"
        )

    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (
                    os.path.basename(file_path),
                    f,
                    config.TripoConfig.SUPPORTED_FILE_TYPES[file_ext],
                )
            }
            response = requests.post(url, headers=headers, files=files)

        if response.status_code == 200:
            return response.json()
        else:
            config.logger.error(f"File upload failed: {response.status_code}")
            raise Exception(f"File upload error: Received response code {response.status_code}")
    except requests.RequestException as e:
        config.logger.error(f"Failed to upload file: {str(e)}")
        raise Exception(f"File upload network error: {str(e)}")


class ProgressTracker:
    """
    Progress tracker for generation process
    """
    def __init__(self, context, is_text_generating=True):
        self.context = context
        self.is_text_generating = is_text_generating
        self.start_time = time.time()

    def __enter__(self):
        if self.is_text_generating:
            self.context.scene.text_model_generating = True
        else:
            self.context.scene.image_model_generating = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_text_generating:
            self.context.scene.text_model_generating = False
            self.context.scene.text_generating_percentage = 0
        else:
            self.context.scene.image_model_generating = False
            self.context.scene.image_generating_percentage = 0

    def update_progress(self, progress, status=None):
        """
        Update progress and status

        Args:
            progress: Progress percentage (0-100)
            status: Status description text
        """
        if self.is_text_generating:
            self.context.scene.text_generating_percentage = progress
        else:
            self.context.scene.image_generating_percentage = progress


def validate_image_file(file_path):
    """
    Validate if an image file is valid

    Args:
        file_path: Image file path

    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return False, "File does not exist"

        # Check file size
        if os.path.getsize(file_path) > config.TripoConfig.MAX_FILE_SIZE:
            return (
                False,
                f"File size exceeds {config.TripoConfig.MAX_FILE_SIZE / 1024 / 1024}MB limit",
            )

        # Check file type
        ext = os.path.splitext(file_path)[1][1:].lower()
        if ext not in config.TripoConfig.SUPPORTED_FILE_TYPES:
            return (
                False,
                f"Unsupported file type. Supported: {', '.join(config.TripoConfig.SUPPORTED_FILE_TYPES.keys())}",
            )

        return True, ""

    except Exception as e:
        return False, f"Error validating file: {str(e)}"


class TaskFactory:
    """
    Factory class for creating various task request data
    """
    @staticmethod
    def create_text_task_data(context, use_custom_face_limit=False):
        """
        Create request data for text-to-model task

        Args:
            context: Blender context
            use_custom_face_limit: Whether to use custom face count limit

        Returns:
            dict: Task request data
        """
        data = {"type": "text_to_model", "model_version": context.scene.model_version}

        # Handle text prompts
        data["prompt"] = context.scene.text_prompts

        # Handle negative prompts
        if context.scene.enable_negative_prompts:
            data["negative_prompt"] = context.scene.negative_prompts

        # Handle V2.0 specific parameters
        if (
            context.scene.model_version == "v2.0-20240919"
        ):
            data.update(
                {
                    "quad": context.scene.quad,
                }
            )

            # Add face count limit
            if use_custom_face_limit and context.scene.face_number > 0:
                data["face_limit"] = int(context.scene.face_number)

        return data

    @staticmethod
    def create_image_task_data(context, file_token, use_custom_face_limit=False):
        """
        Create request data for image-to-model task

        Args:
            context: Blender context
            file_token: File token of the uploaded image
            use_custom_face_limit: Whether to use custom face count limit

        Returns:
            dict: Task request data
        """
        data = {
            "type": "image_to_model",
            "model_version": context.scene.model_version,
            "file": {"type": "jpg", "file_token": file_token},
        }

        # Handle V2.0 specific parameters
        if (
            context.scene.model_version == "v2.0-20240919"
        ):
            # Add V2.0 specific parameters
            data.update(
                {
                    "quad": context.scene.quad,
                }
            )

            # Add face count limit
            if use_custom_face_limit and context.scene.face_number > 0:
                data["face_limit"] = int(context.scene.face_number)

        return data

    @staticmethod
    def create_multiview_task_data(context, file_tokens, use_custom_face_limit=False):
        """
        Create request data for multiview-to-model task

        Args:
            context: Blender context
            file_tokens: List of file tokens for uploaded images
            use_custom_face_limit: Whether to use custom face count limit

        Returns:
            dict: Task request data
        """
        data = {
            "type": "multiview_to_model",
            "model_version": context.scene.model_version,
            "files": [
                {"type": "jpg", "file_token": file_tokens[0]},  # Front
                {"type": "jpg", "file_token": file_tokens[1]},  # Left
                {"type": "jpg", "file_token": file_tokens[2]},  # Back
                {},  # Placeholder
            ],
            "mode": "LEFT",
        }

        # Handle V2.0 specific parameters
        if (
            context.scene.model_version == "v2.0-20240919"
        ):
            data.update(
                {
                    "quad": context.scene.quad,
                }
            )

            # Add face count limit
            if use_custom_face_limit and context.scene.face_number > 0:
                data["face_limit"] = int(context.scene.face_number)

        return data


def calculate_text_to_model_price(scene):
    """
    Calculate the price for a text-to-model task

    Args:
        scene: Blender scene

    Returns:
        int: Price (in points)
    """
    price = 0

    # Get model version
    model_version = scene.model_version

    # Determine base price
    if model_version == "v2.0-20240919":
        price = 20  # V2.0 base price

        # Quad additional fee
        if scene.quad:
            price += 5
    else:
        price = 10  # V1.0 base price

    return price


def calculate_image_to_model_price(scene):
    """
    Calculate the price for an image-to-model task

    Args:
        scene: Blender scene

    Returns:
        int: Price (in points)
    """
    price = 0

    # Get model version
    model_version = scene.model_version

    # Determine base price
    if model_version == "v2.0-20240919":
        # Single view or multiview
        if scene.multiview_generate_mode:
            price = 40  # Multiview base price
        else:
            price = 30  # Single view base price

        # Quad additional fee
        if scene.quad:
            price += 5
    else:
        # V1.0 price
        if scene.multiview_generate_mode:
            price = 30  # Multiview
        else:
            price = 20  # Single view

    return price 
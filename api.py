import requests
import asyncio
import os
import tempfile
import logging
import time
from functools import wraps
import bpy
from .config import TripoConfig, get_logger


def retry_with_backoff(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = TripoConfig.MAX_RETRIES
        retry_delay = 1  # Start with 1 second delay

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.RequestException, TripoAPIError) as e:
                if attempt == max_retries - 1:  # Last attempt
                    raise  # Re-raise the last error

                get_logger().warning(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

    return wrapper


@retry_with_backoff
def fetch_data(url, headers_tuple, method="GET", data=None, files=None):
    headers = dict([headers_tuple[i : i + 2] for i in range(0, len(headers_tuple), 2)])
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
            logging.error(f"Failed to fetch data: {response.status_code}")
            raise Exception(f"API Error: Received response code {response.status_code}")
    except requests.RequestException as e:
        logging.error(f"Network Error: {str(e)}")
        raise


def upload_file(url, headers_tuple, file_path):
    """
    Upload a file to Tripo API

    Args:
        url: Upload endpoint URL
        headers_tuple: Authorization headers
        file_path: Path to the file to upload

    Returns:
        dict: Response from the API containing file_token
    """
    headers = dict([headers_tuple[i : i + 2] for i in range(0, len(headers_tuple), 2)])

    # Validate file exists
    if not os.path.exists(file_path):
        raise TripoValidationError(f"File not found: {file_path}")

    # Validate file size
    file_size = os.path.getsize(file_path)
    if file_size > TripoConfig.MAX_FILE_SIZE:
        raise TripoValidationError(
            f"File size ({file_size} bytes) exceeds maximum allowed size ({TripoConfig.MAX_FILE_SIZE} bytes)"
        )

    # Get file extension and validate type
    file_ext = os.path.splitext(file_path)[1][1:].lower()
    if file_ext not in TripoConfig.SUPPORTED_FILE_TYPES:
        raise TripoValidationError(
            f"Unsupported file type: {file_ext}. Supported types: {', '.join(TripoConfig.SUPPORTED_FILE_TYPES.keys())}"
        )

    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (
                    os.path.basename(file_path),
                    f,
                    TripoConfig.SUPPORTED_FILE_TYPES[file_ext],
                )
            }
            response = requests.post(url, headers=headers, files=files)

        if response.status_code == 200:
            return response.json()
        else:
            raise TripoAPIError.from_response(response)

    except requests.RequestException as e:
        raise TripoNetworkError(f"Failed to upload file: {str(e)}")


class ProgressTracker:
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
        if self.is_text_generating:
            self.context.scene.text_generating_percentage = progress
        else:
            self.context.scene.image_generating_percentage = progress

        if status and hasattr(self.context.scene, "generation_status"):
            self.context.scene.generation_status = status

        if hasattr(self.context.scene, "generation_elapsed_time"):
            elapsed_time = time.time() - self.start_time
            self.context.scene.generation_elapsed_time = elapsed_time


async def receive_one(tid, context, isTextGenerating):
    progress_tracker = ProgressTracker(context, isTextGenerating)

    try:
        with progress_tracker:
            while True:
                base_url = f"{TripoConfig.TASK_ENDPOINT}/{tid}"
                headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")
                data = fetch_data(base_url, headers_tuple)

                status = data.get("data", {}).get("status")
                progress_value = float(data["data"]["progress"])

                progress_tracker.update_progress(
                    progress_value, f"Task {status}: {progress_value}%"
                )
                scn = context.scene
                task_status_array = scn.task_status_array

                # Mark whether the task is found
                task_found = False

                for task in task_status_array:
                    if task.task_id == tid:  # Access using task.task_id
                        task.status = status  # Update status
                        task_found = True
                        break

                if not task_found:
                    # If task not found, add a new task
                    new_task = task_status_array.add()
                    new_task.task_id = tid  # Set task ID
                    new_task.status = status  # Set task status

                if status in [
                    TripoConfig.STATUS_CODES["COMPLETED"],
                    TripoConfig.STATUS_CODES["SUCCESS"],
                ]:
                    Update_User_balance(context.scene.api_key, context)
                    return data
                elif status == TripoConfig.STATUS_CODES["FAILED"]:
                    raise TripoAPIError(
                        f"Task failed: {data.get('data', {}).get('message', 'Unknown error')}"
                    )
                elif status not in [
                    TripoConfig.STATUS_CODES["RUNNING"],
                    TripoConfig.STATUS_CODES["QUEUED"],
                ]:
                    raise TripoAPIError(f"Unknown task status: {status}")

                await asyncio.sleep(TripoConfig.POLLING_INTERVAL)

    except Exception as e:
        logging.error(f"Error in receive_one: {str(e)}")
        raise


def show_error_dialog(error_message):
    def draw(self, context):
        self.layout.label(text=error_message)

    def show_message():
        bpy.context.window_manager.popup_menu(draw, title="Error", icon="ERROR")

    # Schedule the dialog to be shown in the main thread
    bpy.app.timers.register(show_message, first_interval=0.1)


async def search_task(tid, context, isTextGenerating):
    try:
        result = await receive_one(tid, context, isTextGenerating)
        print(result["data"])

        # Extract model URL based on response structure
        glb_model_url = None
        model_type = None
        result_data = result["data"].get("result", {})

        # Check three possible model fields by priority
        model_fields = ["pbr_model", "base_model", "model"]

        if result["data"]["input"]["model_version"] in [
            "v2.0-20240919",
            "v2.5-20250123",
        ]:
            # New version priority check: pbr_model -> base_model -> model
            for field in model_fields:
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break
        else:
            # Old version check order: model -> base_model -> pbr_model
            for field in reversed(model_fields):
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break

        if not glb_model_url:
            raise TripoAPIError(
                "No model URL found in response (checked pbr_model/base_model/model)"
            )
        if isTextGenerating:
            context.scene.text_is_importing_model = True
        else:
            context.scene.image_is_importing_model = True
        await gltf_model_download(glb_model_url, context, isTextGenerating, model_type)

        # Reset states
        if isTextGenerating:
            context.scene.text_model_generating = False
            context.scene.text_generating_percentage = 0
        else:
            context.scene.image_model_generating = False
            context.scene.image_generating_percentage = 0

    except Exception as e:
        error_message = f"Error during task search: {str(e)}. Please check the response or contact support."
        show_error_dialog(error_message)
        # Reset states
        if isTextGenerating:
            context.scene.text_model_generating = False
            context.scene.text_generating_percentage = 0
        else:
            context.scene.image_model_generating = False
            context.scene.image_generating_percentage = 0


async def manager_receive_one(tid, context):
    try:
        scn = context.scene
        while True:
            base_url = f"{TripoConfig.TASK_ENDPOINT}/{tid}"
            headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")
            data = fetch_data(base_url, headers_tuple)
            status = data.get("data", {}).get("status")
            task_status_array = scn.task_status_array

            # Mark whether the task is found
            task_found = False

            for task in task_status_array:
                if task.task_id == tid:  # Access using task.task_id
                    task.status = status  # Update status
                    task_found = True
                    break

            if not task_found:
                # If task not found, add a new task
                new_task = task_status_array.add()
                new_task.task_id = tid  # Set task ID
                new_task.status = status  # Set task status

            if status in [
                TripoConfig.STATUS_CODES["COMPLETED"],
                TripoConfig.STATUS_CODES["SUCCESS"],
            ]:
                Update_User_balance(context.scene.api_key, context)
                return data
            elif status == TripoConfig.STATUS_CODES["FAILED"]:
                raise TripoAPIError(
                    f"Task failed: {data.get('data', {}).get('message', 'Unknown error')}"
                )
            elif status not in [
                TripoConfig.STATUS_CODES["RUNNING"],
                TripoConfig.STATUS_CODES["QUEUED"],
            ]:
                raise TripoAPIError(f"Unknown task status: {status}")

            await asyncio.sleep(TripoConfig.POLLING_INTERVAL)

    except Exception as e:
        logging.error(f"Error in receive_one: {str(e)}")
        raise


async def manager_search_task(tid, context):
    try:
        result = await manager_receive_one(tid, context)
        print(result["data"])

        # Extract model URL based on response structure
        glb_model_url = None
        model_type = None
        result_data = result["data"].get("result", {})

        # Check three possible model fields by priority
        model_fields = ["pbr_model", "base_model", "model"]

        if result["data"]["input"]["model_version"] in [
            "v2.0-20240919",
            "v2.5-20250123",
        ]:
            # New version priority check: pbr_model -> base_model -> model
            for field in model_fields:
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break
        else:
            # Old version check order: model -> base_model -> pbr_model
            for field in reversed(model_fields):
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break

        if not glb_model_url:
            raise TripoAPIError(
                "No model URL found in response (checked pbr_model/base_model/model)"
            )

        await manager_gltf_model_download(glb_model_url, context, model_type)

    except Exception as e:
        error_message = f"Error during task search: {str(e)}. Please check the response or contact support."
        show_error_dialog(error_message)


def Update_User_balance(api_key, context):
    headers_tuple = (
        "Content-Type",
        "application/json",
        "Authorization",
        f"Bearer {api_key}",
    )
    response = fetch_data(TripoConfig.get_balance_url(), headers_tuple)
    context.scene.user_balance = str(response["data"]["balance"])


async def gltf_model_download(model_url, context, isTextGenerating, model_type):
    try:
        # First check the value of context.scene.quad
        if model_type == "fbx":  # If True, use FBX format
            # Set FBX URL here
            fbx_url = model_url  # Replace with your actual FBX file URL
            response = requests.get(fbx_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".fbx", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_fbx_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import FBX model
                        bpy.ops.import_scene.fbx(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # First set rotation mode to Euler XYZ
                            obj.rotation_mode = 'XYZ'
                            # Then rotate to face +Y direction
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                    except Exception as e:
                        logging.error(f"Error during FBX import: {str(e)}")
                        raise

                print("Starting FBX Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_fbx_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download FBX model: {response.status_code}")

        else:  # If False, use GLB format
            response = requests.get(model_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".glb", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_glb_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import GLB model
                        bpy.ops.import_scene.gltf(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # First set rotation mode to Euler XYZ
                            obj.rotation_mode = 'XYZ'
                            # Then rotate to face +Y direction
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                    except Exception as e:
                        logging.error(f"Error during GLB import: {str(e)}")
                        raise

                print("Starting GLB Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_glb_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download GLB model: {response.status_code}")
        if isTextGenerating:
            context.scene.text_is_importing_model = False
        else:
            context.scene.image_is_importing_model = False
    except Exception as e:
        if isTextGenerating:
            context.scene.text_is_importing_model = False
        else:
            context.scene.image_is_importing_model = False
        show_error_dialog(f"Error importing model: {str(e)}")


async def manager_gltf_model_download(model_url, context, model_type):
    try:
        if model_type == "fbx":  # If True, use FBX format
            # Set FBX URL here
            fbx_url = model_url  # Replace with your actual FBX file URL
            response = requests.get(fbx_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".fbx", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_fbx_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import FBX model
                        bpy.ops.import_scene.fbx(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # First set rotation mode to Euler XYZ
                            obj.rotation_mode = 'XYZ'
                            # Then rotate to face +Y direction
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                    except Exception as e:
                        logging.error(f"Error during FBX import: {str(e)}")
                        raise

                print("Starting FBX Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_fbx_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download FBX model: {response.status_code}")

        else:  # If False, use GLB format
            response = requests.get(model_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".glb", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_glb_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import GLB model
                        bpy.ops.import_scene.gltf(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # First set rotation mode to Euler XYZ
                            obj.rotation_mode = 'XYZ'
                            # Then rotate to face +Y direction
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                    except Exception as e:
                        logging.error(f"Error during GLB import: {str(e)}")
                        raise

                print("Starting GLB Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_glb_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download GLB model: {response.status_code}")

    except Exception as e:
        show_error_dialog(f"Error importing model: {str(e)}")


class TripoError(Exception):
    """Base exception for all Tripo API errors"""

    pass


class TripoAPIError(TripoError):
    def __init__(self, message, status_code=None, response=None):
        self.status_code = status_code
        self.response = response
        self.message = message
        super().__init__(self.message)

    @classmethod
    def from_response(cls, response):
        """Create an error from a requests Response object"""
        try:
            error_data = response.json()
            # Try to extract error message from various response formats
            if "message" in error_data:
                message = error_data["message"]
            elif "error" in error_data:
                if isinstance(error_data["error"], str):
                    message = error_data["error"]
                else:
                    message = str(error_data["error"])
            else:
                message = f"API error with status code: {response.status_code}"
        except (ValueError, KeyError):
            message = f"API error with status code: {response.status_code}"

        return cls(message, status_code=response.status_code, response=response)


class TripoNetworkError(TripoError):
    """Raised when network connection issues occur"""

    pass


class TripoValidationError(TripoError):
    """Raised when input validation fails"""

    pass
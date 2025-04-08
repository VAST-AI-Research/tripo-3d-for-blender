import os
import asyncio
import tempfile
import time
import bpy
from functools import wraps
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(os.path.dirname(current_dir), "tripo-python-sdk"))

from tripo3d import TripoClient, TripoAPIError, TaskStatus
from .logger import get_logger


async def receive_one(client, tid, context, isTextGenerating):
    progress_tracker = ProgressTracker(context, isTextGenerating)
    polling_interval = 2
    try:
        with progress_tracker:
            while True:
                task = await client.get_task(tid)
                status = task.status
                progress_value = float(task.progress)

                progress_tracker.update_progress(
                    progress_value, f"Task {status}: {progress_value}%"
                )
                scn = context.scene
                task_status_array = scn.task_status_array

                # Mark whether the task is found
                task_found = False

                for task_item in task_status_array:
                    if task_item.task_id == tid:
                        task_item.status = status
                        task_found = True
                        break

                if not task_found:
                    # If task not found, add a new task
                    new_task = task_status_array.add()
                    new_task.task_id = tid
                    new_task.status = status

                if status in [TaskStatus.SUCCESS]:
                    Update_User_balance(context.scene.api_key, context)
                    return task
                elif status == TaskStatus.FAILED:
                    raise TripoAPIError(
                        code="TASK_FAILED", 
                        message=f"Task failed"
                    )
                elif status == TaskStatus.BANNED:
                    raise TripoAPIError(
                        code="TASK_BANNED", 
                        message=f"Task banned"
                    )
                elif status not in [TaskStatus.QUEUED, TaskStatus.RUNNING]:
                    raise TripoAPIError(
                        code="UNKNOWN_STATUS", 
                        message=f"Unknown task status: {status}"
                    )
                if hasattr(task, 'running_left_time') and task.running_left_time is not None:
                    # Use 80% of the estimated remaining time as the next polling interval
                    polling_interval = max(2, task.running_left_time * 0.5)
                else:
                    polling_interval = polling_interval * 2
                await asyncio.sleep(polling_interval)

    except Exception as e:
        get_logger().error(f"Error in receive_one: {str(e)}")
        raise


def show_error_dialog(error_message):
    def draw(self, context):
        self.layout.label(text=error_message)

    def show_message():
        bpy.context.window_manager.popup_menu(draw, title="Error", icon="ERROR")

    # Schedule the dialog to be shown in the main thread
    bpy.app.timers.register(show_message, first_interval=0.1)


@retry_with_backoff
def Update_User_balance(api_key, context):
    try:
        async with TripoClient(api_key=api_key) as client:
            balance = await client.get_balance()
        context.scene.user_balance = f"{balance.balance:.2f}"
    except Exception as e:
        get_logger().error(f"Error updating user balance: {str(e)}")


async def download(task_id, context, task_type=None):
    try:
        async with TripoClient(api_key=context.scene.api_key) as client:
            task_info = await receive_one(client, task_id, context, task_type == 'text2model')
            if task_type is not None:
                if task_type == 'text2model':
                    context.scene.text_is_importing_model = True
                else:
                    context.scene.image_is_importing_model = True
            with tempfile.TemporaryDirectory() as temp_dir:
                result = await client.download_task_models(task=task_info, output_dir=temp_dir)
                model_file = next(iter(downloaded.values()))
                file_extension = os.path.splitext(model_file)[1].lower()
                if temp_filename.endswith('fbx'):
                    bpy.ops.import_scene.fbx(filepath=temp_filename)
                else:
                    bpy.ops.import_scene.gltf(filepath=temp_filename, merge_vertices=True)
                # Set the viewport shading to material preview
                for area in bpy.context.screen.areas:
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            if space.type == 'VIEW_3D':
                                space.shading.type = 'MATERIAL'
    except Exception as e:
        get_logger().error(f"Error downloading model: {str(e)}")
        show_error_dialog(f"Error downloading model: {str(e)}")
    finally:
        if task_type is not None:
            if task_type == 'text2model':
                context.scene.text_is_importing_model = False
            else:
                context.scene.image_is_importing_model = False


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
        max_retries = 3
        retry_delay = 1  # Initial delay of 1 second

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:  # Last attempt
                    raise  # Re-raise the last error

                config.get_logger().warning(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

    return wrapper


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

        if status and hasattr(self.context.scene, "generation_status"):
            self.context.scene.generation_status = status

        if hasattr(self.context.scene, "generation_elapsed_time"):
            elapsed_time = time.time() - self.start_time
            self.context.scene.generation_elapsed_time = elapsed_time


def calculate_generation_price(scene, task_type):
    """
    Calculate the price for a generation task

    Args:
        scene: Blender scene

    Returns:
        float: The price for the task
    """
    price = 10
    if task_type != 'text2model':
        price += 10

    # 获取模型版本
    if scene.model_version.startswith("v2."):
        if scene.texture:
            price += 10
        if scene.texture_quality == "detailed":
            price += 10
        if scene.quad:
            price += 5
        if scene.style and not scene.multiview_generate_mode:
            price += 5
    else:
        price += 10
    return price

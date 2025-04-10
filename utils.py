import os
import asyncio
import tempfile
import time
import bpy
import datetime
from functools import wraps
import requests

from .tripo3d import TripoClient, TripoAPIError, TaskStatus
from .logger import get_logger

async def receive_one(client, tid, context):
    current_task = None
    for task in context.scene.tripo_tasks:
        if task.task_id == tid:
            current_task = task
            break
    if current_task is None:
        current_task = context.scene.tripo_tasks.add()
        current_task.task_id = tid
        context.scene.tripo_task_index = len(context.scene.tripo_tasks) - 1
    polling_interval = 2
    try:
        while True:
            task = await client.get_task(tid)
            status = task.status

            current_task.update(
                status,
                task.progress
            )
            if not current_task.task_type:
                current_task.task_type = task.type
                if task.type == "text_to_model":
                    current_task.prompt = task.input.get("prompt", "")
                # Convert Unix timestamp to formatted date string
                if hasattr(task, 'create_time') and task.create_time:
                    date_time = datetime.datetime.fromtimestamp(task.create_time)
                    current_task.create_time = date_time.strftime("%Y/%m/%d %H:%M:%S")

            if status in [TaskStatus.SUCCESS]:
                await Update_User_balance(context.scene.api_key, context)
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

                get_logger().warning(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

    return wrapper


@retry_with_backoff
async def Update_User_balance(api_key, context):
    try:
        async with TripoClient(api_key=api_key) as client:
            balance = await client.get_balance()
        context.scene.user_balance = str(int(balance.balance))
    except Exception as e:
        get_logger().error(f"Error updating user balance: {str(e)}")


def download(task_id, context):
    async def _download():
        try:
            async with TripoClient(api_key=context.scene.api_key) as client:
                task_info = await receive_one(client, task_id, context)
                result = await client.download_task_models(task=task_info, output_dir=tempfile.gettempdir())
                model_file = next(iter(result.values()))
                return model_file, task_info
        except Exception as e:
            get_logger().error(f"Error downloading model: {str(e)}")
            show_error_dialog(f"Error downloading model: {str(e)}")
    model_file, task_info = asyncio.run(_download())
    def import_model(model_file):
        # Deselect all objects first
        bpy.ops.object.select_all(action="DESELECT")

        # Store current objects
        existing_objects = set(bpy.data.objects[:])
        # Ensure we're in object mode before import
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if model_file.endswith('fbx'):
            bpy.ops.import_scene.fbx(filepath=model_file)
        else:
            bpy.ops.import_scene.gltf(filepath=model_file, merge_vertices=True)
        # Select only newly added objects
        new_objects = set(bpy.data.objects[:]) - existing_objects
        for obj in new_objects:
            obj.select_set(True)
            obj.rotation_mode = 'XYZ'
            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

        # Set active object to one of the new objects if any were added
        if new_objects:
            bpy.context.view_layer.objects.active = list(new_objects)[0]
        os.remove(model_file)
        return None
    bpy.app.timers.register(lambda: import_model(model_file))
    if task_info.output.rendered_image and bpy.app.version >= (3, 2, 0):
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as temp_image_file:
            try:
                response = requests.get(task_info.output.rendered_image, stream=True, verify=False, proxies=None)
                if response.status_code == 200:
                    for chunk in response.iter_content(chunk_size=8192):
                        temp_image_file.write(chunk)
                temp_image_file.close()

                for task in context.scene.tripo_tasks:
                    if task.task_id == task_id:
                        task.update(render_image=bpy.data.images.load(temp_image_file.name))
                        break
            except Exception as e:
                get_logger().error(f"Error downloading render image: {str(e)}")
    return None


def calculate_generation_price(scene, task_type):
    """
    Calculate the price for a generation task

    Args:
        scene: Blender

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
        if scene.style != "original" and not scene.multiview_generate_mode:
            price += 5
    else:
        price += 10
    return price


def ui_update(self, context):
    if not context.area or context.area.type != "VIEW_3D":
        return None

    # Store last update time to prevent too frequent updates
    current_time = time.time()
    last_update = context.scene.last_ui_update

    # Only update if more than 0.1 seconds have passed
    if current_time - last_update > 0.1:
        for region in context.area.regions:
            if region.type == "UI":
                region.tag_redraw()
        context.scene.last_ui_update = current_time

    return None

def image_update(self, context):
    if self.image is None:
        self.image_path = ""

def front_image_update(self, context):
    if self.front_image is None:
        self.front_image_path = ""

def back_image_update(self, context):
    if self.back_image is None:
        self.back_image_path = ""

def left_image_update(self, context):
    if self.left_image is None:
        self.left_image_path = ""

def right_image_update(self, context):
    if self.right_image is None:
        self.right_image_path = ""

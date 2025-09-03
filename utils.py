import os
import asyncio
import tempfile
import time
import bpy
import datetime
from functools import wraps

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
                progress=task.progress,
                running_left_time=task.running_left_time
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
                # Use 50% of the estimated remaining time as the next polling interval
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


def generation(context, task_type):
    async def submit_and_download():
        try:
            async with TripoClient(api_key=context.scene.api_key) as client:
                task = context.scene.tripo_tasks.add()
                context.scene.tripo_task_index = len(context.scene.tripo_tasks) - 1
                if task_type == "text_to_model":
                    prompt = context.scene.text_prompts
                    if context.scene.use_pose_control:
                        prompt += (
                            f", {context.scene.pose_type.lower()}:"
                            f"{context.scene.head_body_height_ratio}:"
                            f"{context.scene.head_body_width_ratio}:"
                            f"{context.scene.legs_body_height_ratio}:"
                            f"{context.scene.arms_body_length_ratio}:"
                            f"{context.scene.span_of_legs}"
                        )
                    task_id = await client.text_to_model(
                        prompt=prompt,
                        negative_prompt=context.scene.negative_prompts,
                        model_version=context.scene.model_version,
                        face_limit=context.scene.face_limit if context.scene.use_custom_face_limit else None,
                        texture=context.scene.texture,
                        pbr=context.scene.pbr,
                        texture_quality=context.scene.texture_quality,
                        style=context.scene.style if context.scene.style != "original" else None,
                        auto_size=context.scene.auto_size,
                        quad=context.scene.quad
                    )
                    task.init(task_id=task_id,
                              task_type=task_type,
                              prompt=prompt)
                elif task_type == "image_to_model":
                    task_id = await client.image_to_model(
                        image=context.scene.image_path,
                        model_version=context.scene.model_version,
                        face_limit=context.scene.face_limit if context.scene.use_custom_face_limit else None,
                        texture=context.scene.texture,
                        pbr=context.scene.pbr,
                        texture_quality=context.scene.texture_quality,
                        style=context.scene.style if context.scene.style != "original" else None,
                        auto_size=context.scene.auto_size,
                        quad=context.scene.quad
                    )
                    task.init(task_id=task_id,
                              task_type=task_type,
                              input_image=context.scene.image)
                elif task_type == "multiview_to_model":
                    image_paths = [
                        context.scene.front_image_path,
                        context.scene.left_image_path,
                        context.scene.back_image_path,
                        context.scene.right_image_path
                    ]
                    for i in range(len(image_paths)):
                        if not image_paths[i]:
                            image_paths[i] = None
                    task_id = await client.multiview_to_model(
                        images=image_paths,
                        model_version=context.scene.model_version,
                        face_limit=context.scene.face_limit if context.scene.use_custom_face_limit else None,
                        texture=context.scene.texture,
                        pbr=context.scene.pbr,
                        texture_quality=context.scene.texture_quality,
                        auto_size=context.scene.auto_size,
                        quad=context.scene.quad
                    )
                    task.init(task_id=task_id,
                              task_type=task_type,
                              input_image=context.scene.front_image)
                else:
                    task.init(task_id=task_type)
                    task_id = task_type
                task_info = await receive_one(client, task_id, context)
                result = client.download_task_models(task=task_info, output_dir=tempfile.gettempdir())
                render_image_result = None
                if task_info.output.rendered_image and bpy.app.version >= (3, 2, 0):
                    render_image_result = client.download_rendered_image(task=task_info, output_dir=tempfile.gettempdir())
                result = await result
                if render_image_result is not None:
                    render_image_result = await render_image_result
                model_file = next(iter(result.values()))
                return model_file, render_image_result, task_info
        except Exception as e:
            get_logger().error(f"Error downloading model: {str(e)}")
            show_error_dialog(f"Error downloading model: {str(e)}")
    model_file, render_image_result, task_info = asyncio.run(submit_and_download())
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
    if render_image_result is not None:
        for task in context.scene.tripo_tasks:
            if task.task_id == task_info.task_id:
                task.update(render_image=bpy.data.images.load(render_image_result))
                break
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
        if scene.texture or scene.pbr:
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

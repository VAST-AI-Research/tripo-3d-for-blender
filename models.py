import bpy
import tempfile
import threading
import os
import logging
from .config import logger, TripoConfig


class ResourceManager:
    def __init__(self):
        self.temp_files = []

    def create_temp_file(self, suffix=None):
        """Create temporary file"""
        temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        self.temp_files.append(temp_file.name)
        return temp_file

    def cleanup(self):
        """Clean up all temporary files"""
        for file_path in self.temp_files:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception as e:
                logger.error(f"Failed to delete temporary file {file_path}: {str(e)}")
        self.temp_files = []


class TripoAPIClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    def get_balance(self):
        """Get account balance"""
        from .api import fetch_data
        return fetch_data(TripoConfig.get_balance_url(), list(self.headers.items()))

    def create_task(self, data):
        """Create task"""
        from .api import fetch_data
        return fetch_data(TripoConfig.TASK_ENDPOINT, list(self.headers.items()), "POST", data)

    def get_task_status(self, task_id):
        """Get task status"""
        from .api import fetch_data
        return fetch_data(TripoConfig.get_task_url(task_id), list(self.headers.items()))

    def upload_file(self, file_path):
        """Upload file"""
        from .api import upload_file
        return upload_file(TripoConfig.UPLOAD_ENDPOINT, list(self.headers.items()), file_path)


class TaskManager:
    def __init__(self, context, api_client):
        self.context = context
        self.api_client = api_client

    def create_text_task(self, prompt, options=None):
        """Create text to model task"""
        from .api import TripoValidationError
        if not prompt:
            raise TripoValidationError("Prompt cannot be empty")

        task_data = TaskFactory.create_text_task_data(self.context)
        # Override prompt
        task_data["prompt"] = prompt
        # Add other options
        if options:
            task_data.update(options)

        return self.api_client.create_task(task_data)

    def create_image_task(self, image_path, options=None):
        """Create image to model task"""
        from .api import TripoValidationError
        
        # Validate image file
        validate_image_file(image_path)
        
        # Upload image to get token
        upload_result = self.api_client.upload_file(image_path)
        file_token = upload_result["data"]["token"]
        
        # Create task data
        task_data = TaskFactory.create_image_task_data(self.context, file_token)
        
        # Add other options
        if options:
            task_data.update(options)
            
        return self.api_client.create_task(task_data)


class ModelImporter:
    _import_lock = threading.Lock()

    @classmethod
    async def import_model(cls, model_url, api_key, context):
        """Import model"""
        from .api import show_error_dialog
        
        # Use lock to prevent importing multiple models simultaneously
        if not cls._import_lock.acquire(blocking=False):
            show_error_dialog("Already importing a model. Please wait.")
            return False
            
        try:
            import requests
            import tempfile
            import asyncio
            
            # Download model file
            response = requests.get(model_url)
            if response.status_code != 200:
                raise Exception(f"Failed to download model: {response.status_code}")
                
            with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tmp_file:
                tmp_file.write(response.content)
                tmp_path = tmp_file.name
                
                # Import in main thread
                def import_in_main():
                    # Ensure we're in object mode before import
                    if bpy.context.mode != 'OBJECT':
                        bpy.ops.object.mode_set(mode='OBJECT')
                        
                    # Deselect all objects
                    bpy.ops.object.select_all(action="DESELECT")
                    
                    # Store existing objects
                    existing_objects = set(bpy.data.objects[:])
                    
                    # Import GLB model
                    bpy.ops.import_scene.gltf(filepath=tmp_path)
                    
                    # Select and rotate new objects
                    new_objects = set(bpy.data.objects[:]) - existing_objects
                    for obj in new_objects:
                        obj.select_set(True)
                        obj.rotation_mode = 'XYZ'
                        obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees
                        
                    # Make one of the new objects active
                    if new_objects:
                        bpy.context.view_layer.objects.active = list(new_objects)[0]
                        
                # Register import function
                bpy.app.timers.register(import_in_main)
                
                # Clean up temporary files
                def cleanup():
                    try:
                        os.unlink(tmp_path)
                    except Exception as e:
                        logger.error(f"Failed to delete temp file: {str(e)}")
                        
                # Delayed cleanup
                bpy.app.timers.register(cleanup, first_interval=5.0)
                
                return True
                
        except Exception as e:
            show_error_dialog(f"Error importing model: {str(e)}")
            return False
        finally:
            cls._import_lock.release()


class TaskFactory:
    @staticmethod
    def create_text_task_data(context, use_custom_face_limit=False):
        """Create text task data"""
        scene = context.scene
        task_data = {
            "task_type": TripoConfig.TASK_TYPES["TEXT_TO_MODEL"],
            "prompt": scene.text_prompts,
            "model_version": scene.model_version,
            "model_style": "original",
        }

        # Add negative prompts
        if scene.enable_negative_prompts and scene.negative_prompts:
            task_data["negative_prompt"] = scene.negative_prompts

        # Quad output option
        if scene.model_version in ["v2.0-20240919", "v2.5-20250123"] and scene.quad:
            task_data["ext"] = {"quad": True}

        # Add face count limit
        if use_custom_face_limit and scene.face_number > 0:
            task_data["face_number"] = scene.face_number

        return task_data

    @staticmethod
    def create_image_task_data(context, file_token, use_custom_face_limit=False):
        """Create image task data"""
        scene = context.scene
        task_data = {
            "model_version": scene.model_version,
        }

        # Set task type and images based on mode
        if scene.multiview_generate_mode:
            task_data["task_type"] = TripoConfig.TASK_TYPES["MULTIVIEW_TO_MODEL"]
            task_data["front_token"] = scene.front_image_token
            task_data["left_token"] = scene.left_image_token
            task_data["back_token"] = scene.back_image_token
        else:
            task_data["task_type"] = TripoConfig.TASK_TYPES["IMAGE_TO_MODEL"]
            task_data["image_token"] = file_token

        # Quad output option
        if scene.model_version in ["v2.0-20240919", "v2.5-20250123"] and scene.quad:
            task_data["ext"] = {"quad": True}

        # Add face count limit
        if use_custom_face_limit and scene.face_number > 0:
            task_data["face_number"] = scene.face_number

        return task_data

    @staticmethod
    def create_animation_task_data(context, model_url, animation_type):
        """Create animation task data"""
        scene = context.scene
        return {
            "task_type": TripoConfig.TASK_TYPES["ANIMATION"],
            "model_url": model_url,
            "animation_type": animation_type,
            "model_version": scene.model_version,
        }

    @staticmethod
    def create_post_process_task_data(context, model_url, options):
        """Create post-processing task data"""
        scene = context.scene
        task_data = {
            "task_type": TripoConfig.TASK_TYPES["POST_PROCESS"],
            "model_url": model_url,
            "model_version": scene.model_version,
        }
        
        if options:
            task_data.update(options)
            
        return task_data


def validate_config(context):
    """Validate configuration"""
    from .api import TripoValidationError
    
    # Check API key
    if not context.scene.api_key:
        raise TripoValidationError("API key is not set")
        
    # Check model version
    if not context.scene.model_version:
        raise TripoValidationError("Model version is not set")
        
    # Text generation mode check
    if not context.scene.multiview_generate_mode:
        if not context.scene.text_prompts and not context.scene.image_path:
            raise TripoValidationError("No prompt or image set for generation")
    # Multiview mode check
    else:
        if not all([context.scene.front_image_path, context.scene.left_image_path, context.scene.back_image_path]):
            raise TripoValidationError("Not all required images set for multiview generation")
    
    return True


def validate_image_file(file_path):
    """Validate image file"""
    from .api import TripoValidationError
    
    # Check if file exists
    if not os.path.exists(file_path):
        raise TripoValidationError(f"File not found: {file_path}")
        
    # Check file size
    file_size = os.path.getsize(file_path)
    if file_size > TripoConfig.MAX_FILE_SIZE:
        raise TripoValidationError(
            f"File size ({file_size/1024/1024:.2f} MB) exceeds maximum allowed size ({TripoConfig.MAX_FILE_SIZE/1024/1024:.2f} MB)"
        )
        
    # Check file type
    file_ext = os.path.splitext(file_path)[1][1:].lower()
    if file_ext not in TripoConfig.SUPPORTED_FILE_TYPES:
        raise TripoValidationError(
            f"Unsupported file type: {file_ext}. Supported types: {', '.join(TripoConfig.SUPPORTED_FILE_TYPES.keys())}"
        )
    
    return True


class TaskStatus(bpy.types.PropertyGroup):
    task_id: bpy.props.StringProperty(name="Task ID", default="")
    status: bpy.props.StringProperty(name="Status", default="") 
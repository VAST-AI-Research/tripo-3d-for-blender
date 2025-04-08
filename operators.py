import bpy
import asyncio
import os
import tempfile
from .api import search_task, manager_search_task, show_error_dialog, Update_User_balance, TripoValidationError
from .models import TaskFactory


class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Connect to Claude"
    bl_description = "Start the BlenderMCP server to connect with Claude"

    def execute(self, context):
        from .server import BlenderMCPServer
        
        # Get port
        port = context.scene.blendermcp_port
        
        # Create server instance
        if not hasattr(bpy, "blendermcp_server") or bpy.blendermcp_server is None:
            bpy.blendermcp_server = BlenderMCPServer(port=port)
            
        # Start server
        bpy.blendermcp_server.start()
        context.scene.blendermcp_server_running = True
        
        # Notify user
        self.report({"INFO"}, f"MCP Server started on port {port}")
        return {"FINISHED"}


class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop the connection to Claude"
    bl_description = "Stop the connection to Claude"

    def execute(self, context):
        # Stop server
        if hasattr(bpy, "blendermcp_server") and bpy.blendermcp_server is not None:
            bpy.blendermcp_server.stop()
            bpy.blendermcp_server = None
            context.scene.blendermcp_server_running = False
            
            # Notify user
            self.report({"INFO"}, "MCP Server stopped")
            
        return {"FINISHED"}


class DownloadTaskOperator(bpy.types.Operator):
    bl_idname = "my_plugin.download_task"
    bl_label = "Download Task"

    task_id: bpy.props.StringProperty()  # Store task ID

    def execute(self, context):
        # Prerequisite check: is task_id empty
        if not self.task_id:
            self.report({"ERROR"}, "Task ID is empty")
            return {"CANCELLED"}
            
        # Check if API key is configured
        if not context.scene.api_key:
            self.report({"ERROR"}, "API key not configured")
            return {"CANCELLED"}
            
        # Asynchronously execute task search
        asyncio.run(manager_search_task(self.task_id, context))
        
        return {"FINISHED"}


class ResetPoseSettings(bpy.types.Operator):
    bl_idname = "pose.reset_pose_settings"
    bl_label = "Reset Pose Settings"
    bl_description = "Reset all pose parameters to default values"

    def execute(self, context):
        # Reset all parameters to default values
        scn = context.scene
        scn.text_prompts = ""
        scn.negative_prompts = ""
        scn.enable_negative_prompts = False
        scn.multiview_generate_mode = False
        scn.image_path = "----"
        scn.left_image_path = "----"
        scn.front_image_path = "----"
        scn.back_image_path = "----"
        
        self.report({"INFO"}, "Settings reset to default values")
        return {"FINISHED"}


class ShowErrorDialog(bpy.types.Operator):
    bl_idname = "error.show_dialog"
    bl_label = "Error"
    bl_options = {"INTERNAL"}

    error_message: bpy.props.StringProperty()

    def execute(self, context):
        # self.report({'ERROR'}, self.error_message)  # Also log to Blender's reporting system
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.label(text=self.error_message)


class ConfirmApiKeyOperator(bpy.types.Operator):
    bl_idname = "my_plugin.confirm_api_key"
    bl_label = "Confirm API Key"

    def execute(self, context):
        # Get API key
        api_key = context.scene.api_key
        
        # Check if API key is empty
        if not api_key:
            self.report({"ERROR"}, "API key cannot be empty")
            return {"CANCELLED"}
            
        try:
            # Test API key
            Update_User_balance(api_key, context)
            
            # Save API key
            context.scene.api_key_confirmed = True
            self.save_api_key_to_local(api_key)
            
            self.report({"INFO"}, "API key confirmed and saved")
            return {"FINISHED"}
            
        except Exception as e:
            self.report({"ERROR"}, f"Failed to validate API key: {str(e)}")
            context.scene.api_key_confirmed = False
            return {"CANCELLED"}

    def save_api_key_to_local(self, api_key):
        """Save API key to local file"""
        # Get plugin directory
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        key_file = os.path.join(addon_dir, "api_key.txt")
        
        # Save to file
        with open(key_file, "w") as f:
            f.write(api_key)


class SwitchImageModeOperator(bpy.types.Operator):
    bl_idname = "my_plugin.switch_image_mode"
    bl_label = "Confirm API Key"

    def execute(self, context):
        # Switch mode
        context.scene.multiview_generate_mode = not context.scene.multiview_generate_mode
        
        # Display notification based on mode
        if context.scene.multiview_generate_mode:
            self.report({"INFO"}, "Switched to multiview generation mode")
        else:
            self.report({"INFO"}, "Switched to single image generation mode")
            
        return {"FINISHED"}


class GenerateTextModelOperator(bpy.types.Operator):
    bl_idname = "my_plugin.generate_text_model"
    bl_label = "Generate Text Model"

    def execute(self, context):
        try:
            # Validate input
            if not context.scene.text_prompts:
                self.report({"ERROR"}, "Text prompt cannot be empty")
                return {"CANCELLED"}
                
            if context.scene.enable_negative_prompts and not context.scene.negative_prompts:
                self.report({"ERROR"}, "Negative prompt cannot be empty when enabled")
                return {"CANCELLED"}
                
            # Get task data
            task_data = TaskFactory.create_text_task_data(context)
            
            # Send API request
            from .api import fetch_data
            headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")
            response = fetch_data(
                url="https://api.tripo3d.ai/v2/openapi/task",
                headers_tuple=headers_tuple,
                method="POST",
                data=task_data
            )
            
            # Get task ID and start polling
            task_id = response["data"]["task_id"]
            
            # Asynchronously execute task search
            asyncio.run(search_task(task_id, context, True))
            
            self.report({"INFO"}, f"Task created with ID: {task_id}")
            return {"FINISHED"}
            
        except Exception as e:
            self.report({"ERROR"}, f"Failed to generate model: {str(e)}")
            return {"CANCELLED"}


class LoadImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file selected")
            return {"CANCELLED"}
            
        try:
            # Load image
            image = bpy.data.images.load(self.filepath)
            context.scene.preview_image = image
            context.scene.image_path = self.filepath
            
            # Set image path
            self.report({"INFO"}, f"Image loaded: {self.filepath}")
            return {"FINISHED"}
            
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LoadLeftImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_left_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file selected")
            return {"CANCELLED"}
            
        try:
            # Load image
            image = bpy.data.images.load(self.filepath)
            context.scene.left_image = image
            context.scene.left_image_path = self.filepath
            
            # Set image path
            self.report({"INFO"}, f"Left image loaded: {self.filepath}")
            return {"FINISHED"}
            
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LoadFrontImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_front_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file selected")
            return {"CANCELLED"}
            
        try:
            # Load image
            image = bpy.data.images.load(self.filepath)
            context.scene.front_image = image
            context.scene.front_image_path = self.filepath
            
            # Set image path
            self.report({"INFO"}, f"Front image loaded: {self.filepath}")
            return {"FINISHED"}
            
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LoadBackImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_back_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file selected")
            return {"CANCELLED"}
            
        try:
            # Load image
            image = bpy.data.images.load(self.filepath)
            context.scene.back_image = image
            context.scene.back_image_path = self.filepath
            
            # Set image path
            self.report({"INFO"}, f"Back image loaded: {self.filepath}")
            return {"FINISHED"}
            
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class GenerateImageModelOperator(bpy.types.Operator):
    bl_idname = "my_plugin.generate_image_model"
    bl_label = "Generate Image Model"

    def execute(self, context):
        try:
            # Validate API key
            if not context.scene.api_key:
                self.report({"ERROR"}, "API key not configured")
                return {"CANCELLED"}
                
            headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")
            
            # Multiview mode
            if context.scene.multiview_generate_mode:
                # Verify all necessary images are loaded
                required_images = [
                    ("front", context.scene.front_image_path),
                    ("left", context.scene.left_image_path),
                    ("back", context.scene.back_image_path)
                ]
                
                for name, path in required_images:
                    if path == "----" or not os.path.exists(path):
                        self.report({"ERROR"}, f"{name.capitalize()} image not loaded")
                        return {"CANCELLED"}
                        
                # Upload all images and get tokens
                from .api import upload_file
                tokens = {}
                
                for name, path in required_images:
                    try:
                        response = upload_file(
                            url="https://api.tripo3d.ai/v2/openapi/upload",
                            headers_tuple=headers_tuple,
                            file_path=path
                        )
                        tokens[f"{name}_token"] = response["data"]["token"]
                    except Exception as e:
                        self.report({"ERROR"}, f"Failed to upload {name} image: {str(e)}")
                        return {"CANCELLED"}
                        
                # Create task data
                task_data = {
                    "task_type": "multiview_to_model",
                    "model_version": context.scene.model_version,
                    "front_token": tokens["front_token"],
                    "left_token": tokens["left_token"],
                    "back_token": tokens["back_token"]
                }
                
                # Quad output option
                if context.scene.model_version in ["v2.0-20240919", "v2.5-20250123"] and context.scene.quad:
                    task_data["ext"] = {"quad": True}
                
            # Single image mode
            else:
                # Verify image is loaded
                if context.scene.image_path == "----" or not os.path.exists(context.scene.image_path):
                    self.report({"ERROR"}, "No image loaded")
                    return {"CANCELLED"}
                    
                # Upload image and get token
                from .api import upload_file
                try:
                    response = upload_file(
                        url="https://api.tripo3d.ai/v2/openapi/upload",
                        headers_tuple=headers_tuple,
                        file_path=context.scene.image_path
                    )
                    image_token = response["data"]["token"]
                except Exception as e:
                    self.report({"ERROR"}, f"Failed to upload image: {str(e)}")
                    return {"CANCELLED"}
                    
                # Create task data
                task_data = {
                    "task_type": "image_to_model",
                    "model_version": context.scene.model_version,
                    "image_token": image_token
                }
                
                # Quad output option
                if context.scene.model_version in ["v2.0-20240919", "v2.5-20250123"] and context.scene.quad:
                    task_data["ext"] = {"quad": True}
            
            # Send API request
            from .api import fetch_data
            response = fetch_data(
                url="https://api.tripo3d.ai/v2/openapi/task",
                headers_tuple=headers_tuple,
                method="POST",
                data=task_data
            )
            
            # Get task ID and start polling
            task_id = response["data"]["task_id"]
            
            # Asynchronously execute task search
            asyncio.run(search_task(task_id, context, False))
            
            self.report({"INFO"}, f"Task created with ID: {task_id}")
            return {"FINISHED"}
            
        except Exception as e:
            self.report({"ERROR"}, f"Failed to generate model: {str(e)}")
            return {"CANCELLED"}
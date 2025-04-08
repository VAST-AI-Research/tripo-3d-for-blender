import bpy
import asyncio
import os
import tempfile
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(os.path.dirname(current_dir), "tripo-python-sdk"))

from tripo3d import TripoClient
from .utils import Update_User_balance, download


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

        return {"FINISHED"}


class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop the connection to Claude"
    bl_description = "Stop the connection to Claude"

    def execute(self, context):
        # Stop server
        if hasattr(bpy, "blendermcp_server") and bpy.blendermcp_server:
            bpy.blendermcp_server.stop()
            bpy.blendermcp_server = None
            del bpy.types.blendermcp_server
        context.scene.blendermcp_server_running = False

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

        asyncio.create_task(download(self.task_id, context))
        return {"FINISHED"}


class ResetPoseSettings(bpy.types.Operator):
    bl_idname = "pose.reset_pose_settings"
    bl_label = "Reset Pose Settings"
    bl_description = "Reset all pose parameters to default values"

    def execute(self, context):
        # Reset all parameters to default values
        scene = bpy.context.scene
        scene.pose_type = "T-Pose"
        scene.head_body_height_ratio = 1.0
        scene.head_body_width_ratio = 1.0
        scene.legs_body_height_ratio = 1.0
        scene.arms_body_length_ratio = 1.0
        scene.span_of_legs = 9.0
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
        scn = context.scene
        if not scn.api_key.startswith("tsk_"):
            bpy.ops.error.show_dialog(
                "INVOKE_DEFAULT",
                error_message="Invalid API Key! API Key must start with 'tsk_'.",
            )
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
        return {"FINISHED"}


class GenerateTextModelOperator(bpy.types.Operator):
    bl_idname = "my_plugin.generate_text_model"
    bl_label = "Generate Text Model"

    def execute(self, context):
        try:
            async with TripoClient(api_key=context.scene.api_key) as client:
                prompt = context.scene.text_prompts
                if context.scene.use_pose_control:
                    prompt += (
                        f", {context.scene.pose_type}:"
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
                download(task_id, context, "text2model")

            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, f"Failed to generate model: {str(e)}")
            return {"CANCELLED"}


class GenerateImageModelOperator(bpy.types.Operator):
    bl_idname = "my_plugin.generate_image_model"
    bl_label = "Generate Image Model"

    def execute(self, context):
        try:
            async with TripoClient(api_key=context.scene.api_key) as client:
                # Multiview mode
                if context.scene.multiview_generate_mode:
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
                        images=images,
                        model_version=context.scene.model_version,
                        face_limit=context.scene.face_limit if context.scene.use_custom_face_limit else None,
                        texture=context.scene.texture,
                        pbr=context.scene.pbr,
                        texture_quality=context.scene.texture_quality,
                        style=context.scene.style if context.scene.style != "original" else None,
                        auto_size=context.scene.auto_size,
                        quad=context.scene.quad
                    )
                else:
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
                download(task_id, context, "image2model")
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

class LoadLeftImageOperator(LoadImageOperator):
    bl_idname = "my_plugin.load_left_image"

class LoadRightImageOperator(LoadImageOperator):
    bl_idname = "my_plugin.load_right_image"

class LoadFrontImageOperator(LoadImageOperator):
    bl_idname = "my_plugin.load_front_image"

class LoadBackImageOperator(LoadImageOperator):
    bl_idname = "my_plugin.load_back_image"

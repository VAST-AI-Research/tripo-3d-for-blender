import bpy
import asyncio
import os
import threading
import base64
from hashlib import sha256

from .tripo3d import TripoClient
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
    bl_idname = "tripo3d.download_task"
    bl_label = "Download Task"

    task_id: bpy.props.StringProperty()  # Store task ID

    def execute(self, context):
        # Prerequisite check: is task_id empty
        if not self.task_id:
            self.report({"ERROR"}, "Task ID is empty")
            return {"CANCELLED"}
        thread = threading.Thread(target=download, args=(self.task_id, context))
        thread.start()
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
    bl_idname = "tripo3d.confirm_api_key"
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
            asyncio.run(Update_User_balance(scn.api_key, context))

            # Save API key
            context.scene.api_key_confirmed = True
            self.save_api_key_to_local(scn.api_key)

            self.report({"INFO"}, "API key confirmed and saved")
            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, f"Failed to validate API key: {str(e)}")
            context.scene.api_key_confirmed = False
            return {"CANCELLED"}

    def save_api_key_to_local(self, api_key):
        """Save encrypted API key to local file"""
        # Get plugin directory
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        key_file = os.path.join(addon_dir, "api_key.enc")

        # Simple encryption with a machine-specific key
        # Generate a machine-specific key using hostname and username
        machine_id = f"{os.getenv('COMPUTERNAME', '')}{os.getenv('USERNAME', '')}"
        if not machine_id:
            machine_id = "default_key"  # Fallback if no environment variables

        # Generate a stable encryption key from machine ID
        key = sha256(machine_id.encode()).digest()

        # XOR encryption with the key
        encrypted_data = bytearray()
        for i, char in enumerate(api_key.encode()):
            encrypted_data.append(char ^ key[i % len(key)])

        # Base64 encode for storage
        encoded_data = base64.b64encode(encrypted_data)

        # Save to file
        with open(key_file, "wb") as f:
            f.write(encoded_data)


class SwitchImageModeOperator(bpy.types.Operator):
    bl_idname = "tripo3d.switch_image_mode"
    bl_label = "Confirm API Key"

    def execute(self, context):
        # Switch mode
        if not context.scene.multiview_generate_mode and not context.scene.model_version.startswith("v2."):
            bpy.ops.error.show_dialog(
                "INVOKE_DEFAULT",
                error_message="multiview generation is not supported for this model version",
            )
            return {"CANCELLED"}
        context.scene.multiview_generate_mode = not context.scene.multiview_generate_mode
        return {"FINISHED"}


class GenerateTextModelOperator(bpy.types.Operator):
    bl_idname = "tripo3d.generate_text_model"
    bl_label = "Generate Text Model"

    def execute(self, context):
        try:
            async def process():
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
                return task_id, prompt
            task_id, prompt = asyncio.run(process())
            task = context.scene.tripo_tasks.add()
            task.init(task_id=task_id,
                      task_type="text_to_model",
                      prompt=prompt)
            context.scene.tripo_task_index = len(context.scene.tripo_tasks) - 1
            thread = threading.Thread(target=download, args=(task_id, context))
            thread.start()
            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, f"Failed to generate model: {str(e)}")
            return {"CANCELLED"}


class GenerateImageModelOperator(bpy.types.Operator):
    bl_idname = "tripo3d.generate_image_model"
    bl_label = "Generate Image Model"

    def execute(self, context):
        try:
            async def process():
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
                            images=image_paths,
                            model_version=context.scene.model_version,
                            face_limit=context.scene.face_limit if context.scene.use_custom_face_limit else None,
                            texture=context.scene.texture,
                            pbr=context.scene.pbr,
                            texture_quality=context.scene.texture_quality,
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
                return task_id
            task_id = asyncio.run(process())
            task = context.scene.tripo_tasks.add()
            if context.scene.multiview_generate_mode:
                task.init(task_id=task_id,
                          task_type="multiview_to_model",
                          input_image=context.scene.front_image)
            else:
                task.init(task_id=task_id,
                          task_type="image_to_model",
                          input_image=context.scene.image)
            context.scene.tripo_task_index = len(context.scene.tripo_tasks) - 1
            thread = threading.Thread(target=download, args=(task_id, context))
            thread.start()
            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, f"Failed to generate model: {str(e)}")
            return {"CANCELLED"}


class LoadBaseImageOperator(bpy.types.Operator):
    bl_idname = "tripo3d.load_base_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file selected")
            return {"CANCELLED"}

        try:
            # Load image
            image = bpy.data.images.load(self.filepath)
            name = '_'.join(self.bl_idname.split('_')[3:])
            setattr(context.scene, name, image)
            setattr(context.scene, f"{name}_path", self.filepath)

            # Set image path
            self.report({"INFO"}, f"Image loaded: {self.filepath}")
            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

class LoadImageOperator(LoadBaseImageOperator):
    bl_idname = "tripo3d.load_image"

class LoadLeftImageOperator(LoadBaseImageOperator):
    bl_idname = "tripo3d.load_left_image"

class LoadRightImageOperator(LoadBaseImageOperator):
    bl_idname = "tripo3d.load_right_image"

class LoadFrontImageOperator(LoadBaseImageOperator):
    bl_idname = "tripo3d.load_front_image"

class LoadBackImageOperator(LoadBaseImageOperator):
    bl_idname = "tripo3d.load_back_image"

@bpy.app.handlers.persistent
def load_api_key_from_local(dummy):
    import base64
    from hashlib import sha256
    import os

    config_path = os.path.join(os.path.dirname(__file__), "api_key.enc")
    try:
        if os.path.exists(config_path):
            # Generate the same machine-specific key
            machine_id = f"{os.getenv('COMPUTERNAME', '')}{os.getenv('USERNAME', '')}"
            if not machine_id:
                machine_id = "default_key"

            key = sha256(machine_id.encode()).digest()

            # Read and decode the encrypted data
            with open(config_path, "rb") as f:
                encoded_data = f.read()

            encrypted_data = base64.b64decode(encoded_data)

            # Decrypt with XOR
            decrypted_data = bytearray()
            for i, char in enumerate(encrypted_data):
                decrypted_data.append(char ^ key[i % len(key)])

            api_key = decrypted_data.decode()

            bpy.context.scene.api_key = api_key
            bpy.context.scene.api_key_confirmed = True
            from .utils import Update_User_balance
            asyncio.run(Update_User_balance(bpy.context.scene.api_key, bpy.context))
    except Exception as e:
        print(f"Cannot load API Key from local: {str(e)}")

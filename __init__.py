bl_info = {
    "name": "Tripo 3D",
    "author": "VAST",
    "version": (0, 6, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Tripo 3D",
    "description": "AI-Powered 3D Model Generation Addon",
    "category": "3D View",
    "doc_url": "https://www.tripo3d.ai/api",
    "tracker_url": "mailto:support@tripo3d.ai",
}

import bpy
import os
from bpy.props import StringProperty, IntProperty, BoolProperty, FloatProperty, EnumProperty, PointerProperty
import tempfile
import shutil

# Import modules
from . import config
from . import api
from . import models
from . import ui
from . import server
from . import operators


# Property registration function
def register_custom_properties():
    """Register all custom properties"""
    # API key
    bpy.types.Scene.api_key = StringProperty(
        name="API Key",
        description="Tripo 3D API Key",
        default="",
        subtype="PASSWORD"
    )
    
    bpy.types.Scene.api_key_confirmed = BoolProperty(
        name="API Key Confirmed",
        default=False
    )
    
    bpy.types.Scene.user_balance = StringProperty(
        name="User Balance",
        default="----"
    )
    
    bpy.types.Scene.show_api_key_guide = BoolProperty(
        name="Show API Key Guide",
        default=False
    )
    
    # Text to model properties
    bpy.types.Scene.text_prompts = StringProperty(
        name="Text Prompts",
        description="Enter your text prompts for generation",
        default=""
    )
    
    bpy.types.Scene.negative_prompts = StringProperty(
        name="Negative Prompts",
        description="Enter negative prompts to avoid certain features",
        default=""
    )
    
    bpy.types.Scene.enable_negative_prompts = BoolProperty(
        name="Enable Negative Prompts",
        default=False
    )
    
    bpy.types.Scene.text_model_generating = BoolProperty(
        name="Text Model Generating",
        default=False
    )
    
    bpy.types.Scene.text_generating_percentage = FloatProperty(
        name="Text Generating Percentage",
        min=0.0,
        max=100.0,
        default=0.0,
        subtype="PERCENTAGE"
    )
    
    bpy.types.Scene.text_is_importing_model = BoolProperty(
        name="Text Is Importing Model",
        default=False
    )
    
    # Image to model properties
    bpy.types.Scene.multiview_generate_mode = BoolProperty(
        name="Multiview Generate Mode",
        default=False
    )
    
    bpy.types.Scene.image_path = StringProperty(
        name="Image Path",
        default="----"
    )
    
    bpy.types.Scene.left_image_path = StringProperty(
        name="Left Image Path",
        default="----"
    )
    
    bpy.types.Scene.front_image_path = StringProperty(
        name="Front Image Path",
        default="----"
    )
    
    bpy.types.Scene.back_image_path = StringProperty(
        name="Back Image Path",
        default="----"
    )
    
    bpy.types.Scene.left_image_token = StringProperty(
        name="Left Image Token",
        default=""
    )
    
    bpy.types.Scene.front_image_token = StringProperty(
        name="Front Image Token",
        default=""
    )
    
    bpy.types.Scene.back_image_token = StringProperty(
        name="Back Image Token",
        default=""
    )
    
    bpy.types.Scene.image_model_generating = BoolProperty(
        name="Image Model Generating",
        default=False
    )
    
    bpy.types.Scene.image_generating_percentage = FloatProperty(
        name="Image Generating Percentage",
        min=0.0,
        max=100.0,
        default=0.0,
        subtype="PERCENTAGE"
    )
    
    bpy.types.Scene.image_is_importing_model = BoolProperty(
        name="Image Is Importing Model",
        default=False
    )
    
    # Image preview
    bpy.types.Scene.preview_image = PointerProperty(
        type=bpy.types.Image,
        name="Preview Image",
        update=ui.update_preview_image
    )
    
    bpy.types.Scene.left_image = PointerProperty(
        type=bpy.types.Image,
        name="Left Image"
    )
    
    bpy.types.Scene.front_image = PointerProperty(
        type=bpy.types.Image,
        name="Front Image"
    )
    
    bpy.types.Scene.back_image = PointerProperty(
        type=bpy.types.Image,
        name="Back Image"
    )
    
    # Model version selection
    bpy.types.Scene.model_version = EnumProperty(
        name="Model Version",
        items=[
            ("v1.0", "v1.0", "Version 1.0"),
            ("v2.0-20240919", "v2.0", "Version 2.0")
        ],
        default="v2.0-20240919"
    )
    
    # Quad output option
    bpy.types.Scene.quad = BoolProperty(
        name="Quad Mesh Output",
        description="Enable quad mesh output",
        default=False
    )
    
    # Face count limit
    bpy.types.Scene.face_number = IntProperty(
        name="Face Number",
        description="Limit the number of faces in generated model",
        default=0,
        min=0
    )
    
    # MCP server
    bpy.types.Scene.blendermcp_port = IntProperty(
        name="Port",
        description="TCP port for the MCP server",
        default=9876,
        min=1024,
        max=65535
    )
    
    bpy.types.Scene.blendermcp_server_running = BoolProperty(
        name="Server Running",
        default=False
    )
    
    bpy.types.Scene.blendermcp_use_polyhaven = BoolProperty(
        name="Use Poly Haven Assets",
        description="Enable access to Poly Haven assets",
        default=False
    )
    
    bpy.types.Scene.MCP_use_tripo = BoolProperty(
        name="Use Tripo as Asset Generator",
        description="Enable Tripo as asset generator",
        default=True
    )
    
    # Task manager
    bpy.types.Scene.temp_taskid = StringProperty(
        name="Task ID",
        description="Enter task ID to download",
        default=""
    )
    
    # UI update
    bpy.types.Scene.last_ui_update = FloatProperty(
        name="Last UI Update",
        default=0.0
    )
    
    # Register task status property group
    bpy.utils.register_class(models.TaskStatus)
    bpy.types.Scene.task_status_array = bpy.props.CollectionProperty(type=models.TaskStatus)


# Registered class list
classes = [
    # Operators
    operators.BLENDERMCP_OT_StartServer,
    operators.BLENDERMCP_OT_StopServer,
    operators.DownloadTaskOperator,
    operators.ResetPoseSettings,
    operators.ShowErrorDialog,
    operators.ConfirmApiKeyOperator,
    operators.SwitchImageModeOperator,
    operators.GenerateTextModelOperator,
    operators.LoadImageOperator,
    operators.LoadLeftImageOperator,
    operators.LoadFrontImageOperator,
    operators.LoadBackImageOperator,
    operators.GenerateImageModelOperator,
    
    # UI panels
    ui.TRIPOD_PT_TripoPluginManagerPanel,
    ui.TRIPOD_PT_TripoPluginMainPanel,
    ui.ImagePreviewProps,
]


# Register function
def register():
    """Register plugin"""
    # Register classes
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Register properties
    register_custom_properties()
    
    # Register handlers
    register_error_handlers()
    
    # Load API key
    if bpy.app.timers.is_registered(load_api_key_from_local):
        bpy.app.timers.unregister(load_api_key_from_local)
    bpy.app.timers.register(load_api_key_from_local, first_interval=1.0, persistent=True)
    
    # Register save/load handlers
    if save_handler not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_handler)
    if load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_handler)


# Unregister function
def unregister():
    """Unregister plugin"""
    # Unregister handlers
    unregister_error_handlers()
    
    if save_handler in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_handler)
    if load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_handler)
    
    # Stop server
    if hasattr(bpy, "blendermcp_server") and bpy.blendermcp_server is not None:
        bpy.blendermcp_server.stop()
        bpy.blendermcp_server = None
    
    # Unregister classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    # Unregister task status property group
    bpy.utils.unregister_class(models.TaskStatus)


# Save handler
def save_handler(dummy):
    """Save pre-processing"""
    # Save API key
    if hasattr(bpy.context.scene, "api_key") and bpy.context.scene.api_key:
        try:
            addon_dir = os.path.dirname(os.path.realpath(__file__))
            key_file = os.path.join(addon_dir, "api_key.txt")
            with open(key_file, "w") as f:
                f.write(bpy.context.scene.api_key)
        except Exception as e:
            config.logger.error(f"Failed to save API key: {str(e)}")


# Load handler
def load_handler(dummy):
    """Load post-processing"""
    # Load API key
    if hasattr(bpy.context.scene, "api_key"):
        load_api_key_from_local(None)


# Load API key from local
@bpy.app.handlers.persistent
def load_api_key_from_local(dummy):
    """Load API key from local file"""
    try:
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        key_file = os.path.join(addon_dir, "api_key.txt")
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                api_key = f.read().strip()
                if api_key:
                    bpy.context.scene.api_key = api_key
                    bpy.context.scene.api_key_confirmed = True
                    
                    # Update balance
                    try:
                        api.Update_User_balance(api_key, bpy.context)
                    except Exception as e:
                        config.logger.error(f"Failed to update balance: {str(e)}")
    except Exception as e:
        config.logger.error(f"Failed to load API key: {str(e)}")


# Register error handlers
def register_error_handlers():
    """Register error handlers"""
    @bpy.app.handlers.persistent
    def handle_blender_crash(*args):
        """Blender crash handler, cleans up temporary files"""
        # Clean up temporary files
        temp_dir = tempfile.gettempdir()
        for file in os.listdir(temp_dir):
            if file.startswith("tripo_") and file.endswith(".glb"):
                try:
                    os.unlink(os.path.join(temp_dir, file))
                except Exception as e:
                    config.logger.error(f"Failed to delete temporary file {file}: {str(e)}")

    # Register the handler for load_post event
    if handle_blender_crash not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(handle_blender_crash)


def unregister_error_handlers():
    """Unregister error handlers"""
    # Remove all handlers we added
    for handler in bpy.app.handlers.load_post:
        if handler.__name__ == "handle_blender_crash":
            bpy.app.handlers.load_post.remove(handler)


# Register plugin when run directly
if __name__ == "__main__":
    register()

bl_info = {
    "name": "Tripo 3D",
    "author": "VAST",
    "version": (0, 7, 0),
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
from .config import get_logger
from . import api
from . import models
from . import ui
from . import server
from . import operators


class TripoSettings(bpy.types.PropertyGroup):
    api_key: bpy.props.StringProperty(
        name="API Key",
        description="API Key for Tripo 3D",
        default="",
        subtype="PASSWORD",
    )
    api_key_confirmed: bpy.props.BoolProperty(name="API Key Confirmed", default=False)
    user_balance: bpy.props.StringProperty(name="User Balance", default="----")

class TaskStatus(bpy.types.PropertyGroup):
    task_id: bpy.props.StringProperty(name="Task ID", default="")
    status: bpy.props.StringProperty(name="Status", default="")

REGISTERED_PROPERTIES = []
# Property registration function
def register_custom_properties():
    pre_register_props = set(dir(bpy.types.Scene))
    bpy.types.Scene.api_key = bpy.props.StringProperty(
        name="API Key", default="", subtype="PASSWORD"
    )
    bpy.types.Scene.model_version = bpy.props.EnumProperty(
        name="Model Version",
        description="The version of the model you want to use",
        items=[
            (
                "v2.5-20250123",
                "Version 2.5",
                "2025-01-23 version of the model",
            ),
            ("v2.0-20240919", "Version 2.0", "2024-09-19 version of the model"),
            ("v1.4-20240625", "Version 1.4", "2024-06-25 version of the model"),
        ],
        default="v2.5-20250123",
    )
    bpy.types.Scene.show_api_key_guide = bpy.props.BoolProperty(
        name="show_api_key_guide", default=False
    )
    bpy.types.Scene.api_key_confirmed = bpy.props.BoolProperty(
        name="API Key Confirmed", default=False
    )
    bpy.types.Scene.text_prompts = bpy.props.StringProperty(
        name="Text Prompts", default=""
    )
    bpy.types.Scene.text_prompts_with_pose = bpy.props.StringProperty(
        name="Text Prompts with pose", default=""
    )
    bpy.types.Scene.user_balance = bpy.props.StringProperty(
        name="user_balance", default=""
    )
    bpy.types.Scene.enable_negative_prompts = bpy.props.BoolProperty(
        name="enable_negative_prompts", default=False
    )
    bpy.types.Scene.negative_prompts = bpy.props.StringProperty(
        name="negative_prompts", default=""
    )
    bpy.types.Scene.show_advance_settings = bpy.props.BoolProperty(
        name="Show_advance_settings", default=False
    )
    bpy.types.Scene.text_is_importing_model = bpy.props.BoolProperty(
        name="text_is_importing_model", default=False
    )
    bpy.types.Scene.image_is_importing_model = bpy.props.BoolProperty(
        name="image_is_importing_model", default=False
    )
    bpy.types.Scene.MCP_use_tripo = bpy.props.BoolProperty(
        name="MCP_use_tripo", default=True
    )
    bpy.types.Scene.task_status_array = bpy.props.CollectionProperty(type=TaskStatus)
    bpy.types.Scene.temp_taskid = bpy.props.StringProperty(
        name="temp_taskid", default=""
    )

    bpy.types.Scene.multiview_generate_mode = bpy.props.BoolProperty(
        name="multiview_generate_mode",
        description="Switch the model of image to model between single image and multi-views.",
        default=False,
    )

    # Face Limit
    bpy.types.Scene.use_custom_face_limit = bpy.props.BoolProperty(
        name="use_custom_face_limit",
        description="Enable customized face limit settings.",
        default=False,
    )

    bpy.types.Scene.face_limit = bpy.props.IntProperty(
        name="Face Limit",
        description="Limits the number of faces on the output model. If this option is not set, the face limit will be adaptively determined.",
        default=10000,  # Use -1 to indicate not set
        min=1000,
        max=500000,
        step=1000,
    )
    bpy.types.Scene.quad = bpy.props.BoolProperty(
        name="Quad-mesh",
        description="quad (Optional): Set True to enable quad mesh output. If quad=True and the default face_limit will be 10000. face_limit is not set",
        default=False,
    )

    # Texture
    bpy.types.Scene.texture = bpy.props.BoolProperty(
        name="Texture",
        description="A boolean option to enable texturing. The default value is True, set False to get a base model without any textures.",
        default=True,
    )

    # PBR
    bpy.types.Scene.pbr = bpy.props.BoolProperty(
        name="PBR",
        description="A boolean option to enable pbr. The default value is True, set False to get a model without pbr. If this option is set to True, texture will be ignored and used as True.",
        default=True,
    )

    # Texture Seed
    bpy.types.Scene.texture_seed = bpy.props.IntProperty(
        name="Texture Seed",
        description="This is the random seed for texture generation in version v2.0-20240919. Using the same seed will produce identical textures. This parameter is an integer and is randomly chosen if not set. If you want a model with different textures, please use the same model_seed and different texture_seed.",
        default=0,
        min=0,
    )

    # Texture Alignment
    bpy.types.Scene.texture_alignment = bpy.props.EnumProperty(
        name="Texture Alignment",
        description="Determines the prioritization of texture alignment in the 3D model.",
        items=[
            (
                "original_image",
                "Original Image",
                "Prioritizes visual fidelity to the source image. This option produces textures that closely resemble the original image but may result in minor 3D inconsistencies.",
            ),
            (
                "geometry",
                "Geometry",
                "Prioritizes 3D structural accuracy. This option ensures better alignment with the model's geometry but may cause slight deviations from the original image appearance.",
            ),
        ],
        default="original_image",
    )

    # Texture Quality
    bpy.types.Scene.texture_quality = bpy.props.EnumProperty(
        name="Texture Quality",
        description="This parameter controls the texture quality.",
        items=[
            ("standard", "Standard", "Standard texture quality."),
            (
                "detailed",
                "Detailed",
                "Provides high-resolution textures, resulting in more refined and realistic representation of intricate parts.",
            ),
        ],
        default="standard",
    )

    # Auto Size
    bpy.types.Scene.auto_size = bpy.props.BoolProperty(
        name="Auto Size",
        description="Automatically scale the model to real-world dimensions, with the unit in meters. The default value is False.",
        default=False,
    )

    # Style
    bpy.types.Scene.style = bpy.props.EnumProperty(
        name="Style",
        description="Defines the artistic style or transformation to be applied to the 3D model, altering its appearance according to preset options. Omit this option to keep the original style and appearance.",
        items=[
            (
                "original",
                "Original style",
                "Keep the original style and appearance"
            ),
            (
                "person:person2cartoon",
                "Cartoon",
                "Transforms the model into a cartoon-style version of the input character.",
            ),
            (
                "object:clay",
                "Clay",
                "Applies a clay-like appearance to the object."
            ),
            (
                "object:steampunk",
                "Steampunk",
                "Applies a steampunk aesthetic with metallic gears and vintage details.",
            ),
            (
                "animal:venom",
                "Venom",
                "Applies a venom-like, dark, and glossy appearance to the animal model, BTW, very horrible.",
            ),
            (
                "object:barbie",
                "Barbie",
                "Applies a barbie style to the object."
            ),
            (
                "object:christmas",
                "Christmas",
                "Applies a christmas style to the object.",
            ),
        ],
        default="original",
    )

    # Orientation
    bpy.types.Scene.orientation = bpy.props.EnumProperty(
        name="Orientation",
        description="Set orientation=align_image to automatically rotate the model to align the original image. The default value is default.",
        items=[
            ("default", "Default", "Default orientation."),
            (
                "align_image",
                "Align Image",
                "Automatically rotate the model to align the original image.",
            ),
        ],
        default="default",
    )

    # File filter (only show these file types in the file selection dialog)
    bpy.types.Scene.image_path = bpy.props.StringProperty(
        name="image_path", default=""
    )
    bpy.types.Scene.front_image_path = bpy.props.StringProperty(
        name="front_image_path", default=""
    )
    bpy.types.Scene.left_image_path = bpy.props.StringProperty(
        name="left_image_path", default=""
    )
    bpy.types.Scene.back_image_path = bpy.props.StringProperty(
        name="back_image_path", default=""
    )
    bpy.types.Scene.right_image_path = bpy.props.StringProperty(
        name="right_image_path", default=""
    )
    bpy.types.Scene.filter_glob = bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.gif", options={"HIDDEN"}
    )
    bpy.types.Scene.text_model_generating = bpy.props.BoolProperty(
        name="text_model_generating", default=False, update=ui_update
    )
    bpy.types.Scene.text_generating_percentage = bpy.props.FloatProperty(
        name="text_generating_percentage",
        description="A percentage value for generating",
        default=0.0,
        min=0.0,
        max=100.0,
        update=ui_update,
    )
    bpy.types.Scene.image_model_generating = bpy.props.BoolProperty(
        name="image_model_generating", default=False, update=ui_update
    )
    bpy.types.Scene.image_generating_percentage = bpy.props.FloatProperty(
        name="image_generating_percentage",
        description="A percentage value for generating",
        default=0.0,
        min=0.0,
        max=100.0,
        update=ui_update,
    )
    bpy.types.Scene.template_image = bpy.props.PointerProperty(type=bpy.types.Image)
    bpy.types.Scene.preview_image = bpy.props.PointerProperty(type=bpy.types.Image)
    bpy.types.Scene.front_image = bpy.props.PointerProperty(type=bpy.types.Image)
    bpy.types.Scene.left_image = bpy.props.PointerProperty(type=bpy.types.Image)
    bpy.types.Scene.back_image = bpy.props.PointerProperty(type=bpy.types.Image)
    bpy.types.Scene.right_image = bpy.props.PointerProperty(type=bpy.types.Image)

    bpy.types.Scene.upload_image_props = bpy.props.PointerProperty(
        type=ImagePreviewProps,
        description="The properties of the image preview",
    )

    bpy.types.Scene.last_ui_update = bpy.props.FloatProperty(
        name="Last UI Update Time", default=0.0
    )

    # Add these new properties
    bpy.types.Scene.generation_elapsed_time = bpy.props.FloatProperty(
        name="Generation Elapsed Time",
        description="Time elapsed since generation started",
        default=0.0,
        min=0.0,
    )

    bpy.types.Scene.generation_status = bpy.props.StringProperty(
        name="Generation Status",
        description="Current status of the generation process",
        default="",
    )
    bpy.types.Scene.use_pose_control = bpy.props.BoolProperty(
        name="Enable Pose Control",
        description="Enable control over the model's pose",
        default=False,
    )
    bpy.types.Scene.pose_type = bpy.props.EnumProperty(
        name="Pose Type",
        description="Select the pose type",
        items=[("T-Pose", "T-Pose", ""), ("A-Pose", "A-Pose", "")],
        default="T-Pose",
    )
    bpy.types.Scene.head_body_height_ratio = bpy.props.FloatProperty(
        name="Head-Body Height Ratio",
        description="Ratio of head height to body height",
        default=1.0,
        min=0.1,
        max=5.0,
        step=0.1,
    )
    bpy.types.Scene.head_body_width_ratio = bpy.props.FloatProperty(
        name="Head-Body Width Ratio",
        description="Ratio of head width to body width",
        default=1.0,
        min=0.1,
        max=5.0,
        step=0.1,
    )
    bpy.types.Scene.legs_body_height_ratio = bpy.props.FloatProperty(
        name="Legs-Body Height Ratio",
        description="Ratio of legs height to body height",
        default=1.0,
        min=0.1,
        max=5.0,
        step=0.1,
    )
    bpy.types.Scene.arms_body_length_ratio = bpy.props.FloatProperty(
        name="Arms-Body Length Ratio",
        description="Ratio of arms length to body length",
        default=1.0,
        min=0.1,
        max=5.0,
        step=0.1,
    )
    bpy.types.Scene.span_of_legs = bpy.props.FloatProperty(
        name="Span of Two Legs",
        description="Distance between two legs",
        default=9.0,
        min=0.0,
        max=15.0,
        step=0.1,
    )
    post_register_props = set(dir(bpy.types.Scene))
    global REGISTERED_PROPERTIES
    REGISTERED_PROPERTIES = list(post_register_props - pre_register_props)


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
    operators.LoadRightImageOperator,
    operators.LoadFrontImageOperator,
    operators.LoadBackImageOperator,
    operators.GenerateImageModelOperator,
    operators.MyModelVersionSelector,
    config.TripoSettings,
    TaskStatus,
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

    bpy.types.Scene.tripo_settings = bpy.props.PointerProperty(type=config.TripoSettings)
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

    global REGISTERED_PROPERTIES
    for prop_name in REGISTERED_PROPERTIES:
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)

    REGISTERED_PROPERTIES = []


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
            get_logger().exception(f"Failed to save API key: {str(e)}")


# Load handler
def load_handler(dummy):
    """Load post-processing"""
    scene = bpy.context.scene
    # Load API key
    if hasattr(bpy.context.scene, "api_key"):
        Update_User_balance(scene.api_key, bpy.context)


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
                        get_logger().exception(f"Failed to update balance: {str(e)}")
    except Exception as e:
        get_logger().exception(f"Failed to load API key: {str(e)}")


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
                    get_logger().error(f"Failed to delete temporary file {file}: {str(e)}")

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

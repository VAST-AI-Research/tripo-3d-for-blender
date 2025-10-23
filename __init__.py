bl_info = {
    "name": "Tripo 3D",
    "author": "VAST",
    "version": (0, 7, 6),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Tripo 3D",
    "description": "AI-Powered 3D Model Generation Addon",
    "category": "3D View",
    "doc_url": "https://www.tripo3d.ai/api",
    "tracker_url": "mailto:support@tripo3d.ai",
}

import bpy
from .operators import load_api_key_from_local
from .task import TaskPropertyGroup

REGISTERED_PROPERTIES = []
# Property registration function
def register_custom_properties():
    from .utils import ui_update
    pre_register_props = set(dir(bpy.types.Scene))
    bpy.types.Scene.api_key = bpy.props.StringProperty(
        name="API Key", default="", subtype="PASSWORD"
    )
    bpy.types.Scene.model_version = bpy.props.EnumProperty(
        name="Model Version",
        description="The version of the model you want to use",
        items=[
            ("v3.0-20250812", "Version 3.0", "2025-08-12 version of the model"),
            ("v2.5-20250123", "Version 2.5", "2025-01-23 version of the model"),
            ("v2.0-20240919", "Version 2.0", "2024-09-19 version of the model"),
            ("v1.4-20240625", "Version 1.4", "2024-06-25 version of the model"),
        ],
        default="v3.0-20250812",
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
        max=2000000,
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

    # Geometry Quality
    bpy.types.Scene.geometry_quality = bpy.props.EnumProperty(
        name="Geometry Quality",
        description="This parameter controls the geometry quality.",
        items=[
            ("standard", "Standard", "Standard geometry quality."),
            ("detailed", "Detailed", "Detailed geometry quality."),
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
    from .utils import image_update, front_image_update, back_image_update, left_image_update, right_image_update
    bpy.types.Scene.image = bpy.props.PointerProperty(type=bpy.types.Image, update=image_update)
    bpy.types.Scene.front_image = bpy.props.PointerProperty(type=bpy.types.Image, update=front_image_update)
    bpy.types.Scene.left_image = bpy.props.PointerProperty(type=bpy.types.Image, update=left_image_update)
    bpy.types.Scene.back_image = bpy.props.PointerProperty(type=bpy.types.Image, update=back_image_update)
    bpy.types.Scene.right_image = bpy.props.PointerProperty(type=bpy.types.Image, update=right_image_update)

    bpy.types.Scene.last_ui_update = bpy.props.FloatProperty(
        name="Last UI Update Time", default=0.0
    )

    bpy.types.Scene.temp_taskid = bpy.props.StringProperty(
        name="temp_taskid", default=""
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
    bpy.types.Scene.tripo_tasks = bpy.props.CollectionProperty(type=TaskPropertyGroup)
    bpy.types.Scene.tripo_task_index = bpy.props.IntProperty(default=-1)
    post_register_props = set(dir(bpy.types.Scene))
    global REGISTERED_PROPERTIES
    REGISTERED_PROPERTIES = list(post_register_props - pre_register_props)


# Register function
def register():
    """Register plugin"""
    if bpy.app.version < bl_info["blender"]:
        msg = (
            f"Addon requires Blender {'.'.join(map(str, bl_info['blender']))} or newer"
        )
        raise Exception(msg)

    bpy.types.Scene.blendermcp_port = bpy.props.IntProperty(
        name="Port",
        description="Port for the BlenderMCP server",
        default=9876,
        min=1024,
        max=65535,
    )

    bpy.types.Scene.blendermcp_server_running = bpy.props.BoolProperty(
        name="Server Running", default=False
    )

    bpy.types.Scene.blendermcp_use_polyhaven = bpy.props.BoolProperty(
        name="Use Poly Haven",
        description="Enable Poly Haven asset integration",
        default=False,
    )

    global classes
    from . import ui
    from . import operators

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
        TaskPropertyGroup,
        # UI panels
        ui.TRIPOD_PT_TripoPluginManagerPanel,
        ui.TRIPOD_PT_TripoPluginMainPanel,
        ui.SelectTaskOperator,
        ui.TaskSubmittedMessageOperator,
    ]
    # Register classes
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register properties
    register_custom_properties()

    # Register save/load handlers
    if load_api_key_from_local not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_api_key_from_local)


# Unregister function
def unregister():
    """Unregister plugin"""

    if load_api_key_from_local in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_api_key_from_local)

    # Stop server
    if hasattr(bpy, "blendermcp_server") and bpy.blendermcp_server is not None:
        bpy.blendermcp_server.stop()
        bpy.blendermcp_server = None

    # Unregister classes
    global classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    global REGISTERED_PROPERTIES
    for prop_name in REGISTERED_PROPERTIES:
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)

    from .logger import close_logger
    close_logger()
    REGISTERED_PROPERTIES = []


# Register plugin when run directly
if __name__ == "__main__":
    register()

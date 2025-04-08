import bpy
import textwrap
import time
from .config import TripoConfig


class TRIPOD_PT_TripoPluginManagerPanel(bpy.types.Panel):
    bl_idname = "TRIPOD_PT_Manage_panel"
    bl_label = "Tripo 3D Manager"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tripo Model Manager"

    def draw(self, context):
        layout = self.layout
        scn = context.scene

        box = layout.box()
        # Draw header
        row = box.row()
        row.label(text="TaskID:")
        row.label(text="Status:")
        row.label(text="Options:")

        # Read task status stored in the scene
        for task in scn.task_status_array:
            row = box.row()
            row.label(text=task.task_id)  # Use task.task_id
            row.label(text=task.status)  # Use task.status
            if task.status == "failed":
                row.operator(
                    DownloadTaskOperator.bl_idname, text="Retry"
                ).task_id = task.task_id
            else:
                row.operator(
                    DownloadTaskOperator.bl_idname, text="Download"
                ).task_id = task.task_id
            if task.status == "running" or task.status == "queued":
                row.enabled = False
        box = layout.box()
        row = box.row()
        row.label(text="Add custom task:")
        row = box.row()
        row.prop(context.scene, "temp_taskid", text="")
        row.operator(
            DownloadTaskOperator.bl_idname, text="Search and add"
        ).task_id = scn.temp_taskid

    def add_task(self, task_id, status, scene):
        """Add new task to the scene"""
        task_status_array = scene.task_status_array

        # Add new task
        new_task = task_status_array.add()
        new_task.task_id = task_id
        new_task.status = status

    def refresh_tasks(self, context):
        """Refresh task status"""
        scn = context.scene
        task_status_array = scn.task_status_array

        for task in task_status_array:
            task_id = task.task_id
            # Should call real API to get task status
            # status = get_task_status(task_id)
            status = "NEW_STATUS"  # Assume you get new status from API
            # Update status
            task.status = status  # Update status


class TRIPOD_PT_TripoPluginMainPanel(bpy.types.Panel):
    bl_idname = "TRIPOD_PT_Generate_panel"
    bl_label = "Tripo 3D Generator"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tripo Model Generator"

    def draw(self, context):
        layout = self.layout
        scn = context.scene

        # API KEY input section
        row = layout.row()
        row.label(text="User Balance:")
        row.label(text=scn.user_balance)
        row.operator(
            "wm.url_open", text="Go Billing"
        ).url = "https://platform.tripo3d.ai/billing"
        row = layout.row()
        row.label(text="API_KEY:")
        row.prop(context.scene, "api_key", text="")

        row = layout.row()
        row.operator("my_plugin.confirm_api_key", text="Confirm")

        if not context.scene.api_key_confirmed:
            row = layout.row()
            row.prop(
                scn,
                "show_api_key_guide",
                icon="HIDE_OFF" if scn.show_api_key_guide else "HIDE_ON",
                text="How To Get Your API Key",
                emboss=False,
            )
            if scn.show_api_key_guide:
                row = layout.row()
                row.label(text="1. Click the button below to visit Tripo API platform")
                row = layout.row()
                row.operator(
                    "wm.url_open", text="Visit Tripo API Platform"
                ).url = "https://platform.tripo3d.ai/api-keys"
                row = layout.row()
                row.label(text="2. Login into your account")
                row = layout.row()
                row.label(text="3. Apply the API key and click to copy")

        if context.scene.api_key_confirmed:
            layout.label(text="")
            mcp_box = layout.box()
            row = mcp_box.row(align=True)
            row.alignment = "CENTER"
            row.label(text="MCP Connections")
            row = mcp_box.row()
            row.prop(scn, "blendermcp_port")
            row = mcp_box.row()
            row.prop(scn, "blendermcp_use_polyhaven", text="Use assets from Poly Haven")
            row = mcp_box.row()
            row.enabled = False
            row.prop(scn, "MCP_use_tripo", text="Use Tripo as assets generator")
            if not scn.blendermcp_server_running:
                mcp_box.operator("blendermcp.start_server", text="Start MCP Server")
            else:
                mcp_box.operator("blendermcp.stop_server", text="Stop MCP Server")
                mcp_box.label(text=f"Running on port {scn.blendermcp_port}")

            layout.label(text="")
            box = layout.box()
            row = box.row(align=True)  # Create a centered row layout
            row.alignment = "CENTER"
            row.label(text="Text_to_Model")
            row = box.row()
            row.label(text="Text prompts:")
            row = box.row()
            row.prop(context.scene, "text_prompts", text="")
            row = box.row()
            row.prop(scn, "enable_negative_prompts", text="Enable negative prompts")
            if scn.enable_negative_prompts:
                row = box.row()
                row.label(text="Negative prompts:")
                row = box.row()
                row.prop(context.scene, "negative_prompts", text="")

            row = box.row()
            if (
                not context.scene.enable_negative_prompts
                and context.scene.text_prompts == ""
            ) or (
                (
                    context.scene.negative_prompts == ""
                    or context.scene.text_prompts == ""
                )
                and context.scene.enable_negative_prompts
            ):
                row.enabled = False
                row.operator(
                    "my_plugin.generate_text_model",
                    text=f"Generate (cost:{calculate_text_to_model_price(scn)})",
                )
            else:
                row.operator(
                    "my_plugin.generate_text_model",
                    text=f"Generate (cost:{calculate_text_to_model_price(scn)})",
                )
            if context.scene.text_model_generating:
                box.label(text="Task Generating...")
                box.prop(
                    context.scene, "text_generating_percentage", text="", slider=True
                )
            else:
                box.label(text="No Task Generating")
            if scn.text_is_importing_model:
                row = box.row()
                row.label(text="Import Model...")

            layout.label(text="")
            box = layout.box()
            row = box.row(align=True)
            row.alignment = "CENTER"
            row.label(text="Image_to_Model")

            if not scn.multiview_generate_mode:
                row = box.row()
                row.operator(
                    "my_plugin.switch_image_mode", text="Switch to multiview mode"
                )
                row = box.row()
                if scn.image_path == "----":
                    split = row.split(factor=0.33)
                    col = split.column(align=True)
                    col = split.column(align=True)
                    row = col.row()
                    row.template_ID_preview(
                        scn, "preview_image", open="my_plugin.load_image"
                    )
                    col = split.column(align=True)
                else:
                    row.template_ID_preview(
                        scn, "preview_image", open="my_plugin.load_image"
                    )
                row = box.row()
                row.label(text="Image Selected: ")
                row.label(text=scn.image_path)
                row = box.row()
            elif (
                scn.model_version == "v2.0-20240919"
                or scn.model_version == "v2.5-20250123"
            ) and scn.multiview_generate_mode:
                row = box.row()
                row.operator(
                    "my_plugin.switch_image_mode", text="Switch to single image mode"
                )

                # First row - FRONT and RIGHT images
                row = box.row()
                split = row.split(factor=0.5)

                # FRONT IMAGE
                col_front = split.column(align=True)
                label_row = col_front.row()
                label_row.alignment = "CENTER"
                label_row.label(text="FRONT")
                row = col_front.row()
                row.template_ID_preview(
                    scn, "front_image", open="my_plugin.load_front_image"
                )

                # RIGHT IMAGE
                col_right = split.column(align=True)
                label_row = col_right.row()
                label_row.alignment = "CENTER"
                label_row.label(text="RIGHT")
                row = col_right.row()
                row.template_ID_preview(
                    scn, "right_image", open="my_plugin.load_right_image"
                )

                # Second row - LEFT and BACK images
                row = box.row()
                split = row.split(factor=0.5)

                # LEFT IMAGE
                col_left = split.column(align=True)
                label_row = col_left.row()
                label_row.alignment = "CENTER"
                label_row.label(text="LEFT")
                row = col_left.row()
                row.template_ID_preview(
                    scn, "left_image", open="my_plugin.load_left_image"
                )

                # BACK IMAGE
                col_back = split.column(align=True)
                label_row = col_back.row()
                label_row.alignment = "CENTER"
                label_row.label(text="BACK")
                row = col_back.row()
                row.template_ID_preview(
                    scn, "back_image", open="my_plugin.load_back_image"
                )

                row = box.row()
            else:
                row = box.row()
                row.operator(
                    "my_plugin.switch_image_mode", text="Switch to single image mode"
                )
                row = box.row()
                _label_multiline(
                    context=context,
                    text="\nThe multi-view generation feature in versions 1.3 and 1.4 will soon be discontinued to make way for version 2.5. Please look forward to the amazing performance of version 2.5!\n",
                    parent=box,
                )
                row = box.row()

            if (
                (
                    not (
                        context.scene.model_version == "v2.0-20240919"
                        or context.scene.model_version == "v2.5-20250123"
                    )
                    and scn.multiview_generate_mode
                )
                or (
                    (context.scene.image_path == "----" and context.scene.preview_image is None)
                    and not context.scene.multiview_generate_mode
                )
                or (
                    context.scene.multiview_generate_mode
                    and (
                        (context.scene.left_image_path == "----" and context.scene.left_image is None)
                        or (context.scene.front_image_path == "----" and context.scene.front_image is None)
                        or (context.scene.back_image_path == "----" and context.scene.back_image is None)
                    )
                )
            ):
                row.enabled = False
                row.operator(
                    "my_plugin.generate_image_model",
                    text=f"Generate (cost:{calculate_image_to_model_price(scn)})",
                )
            else:
                row.operator(
                    "my_plugin.generate_image_model",
                    text=f"Generate (cost:{calculate_image_to_model_price(scn)})",
                )
            if context.scene.image_model_generating:
                box.label(text="Task Generating...")
                box.prop(
                    context.scene, "image_generating_percentage", text="", slider=True
                )
            else:
                box.label(text="No Task Generating")
            if scn.image_is_importing_model:
                row = box.row()
                row.label(text="Import Model...")

            layout.label(text="")
            post_process_box = layout.box()
            row = post_process_box.row(align=True)
            row.alignment = "CENTER"
            row.label(text="Settings")

            row = post_process_box.row()
            row.label(text="Model Version")
            row.prop(context.scene, "model_version", text="")
            if (
                scn.model_version == "v2.0-20240919"
                or scn.model_version == "v2.5-20250123"
            ):
                row = post_process_box.row()
                row.prop(scn, "quad", text="Enable quad mesh output")
                # row.enabled = False
            row = post_process_box.row()
            row.prop(scn, "use_custom_face_limit", text="Use custom face limit")
            row = post_process_box.row()
            row.prop(scn, "face_limit", text="Face Limit")
            row.enabled = scn.use_custom_face_limit
            row = post_process_box.row()
            row.prop(scn, "style", text="Style")

            row = post_process_box.row()
            row.prop(scn, "use_pose_control", text="Enable Pose Control")
            if scn.use_pose_control:
                row.operator(ResetPoseSettings.bl_idname, text="Reset Pose Control")

            if scn.use_pose_control:
                # Dropdown to select T-pose or A-pose
                row = post_process_box.row()
                row.prop(scn, "pose_type", text="Pose Type")

                # Slider to adjust head-body height ratio
                row = post_process_box.row()
                row.prop(scn, "head_body_height_ratio", text="Head-Body Height Ratio")
                # Slider to adjust head-body width ratio
                row = post_process_box.row()
                row.prop(scn, "head_body_width_ratio", text="Head-Body Width Ratio")
                # Slider to adjust legs-body height ratio
                row = post_process_box.row()
                row.prop(scn, "legs_body_height_ratio", text="Legs-Body Height Ratio")
                # Slider to adjust arms-body length ratio
                row = post_process_box.row()
                row.prop(scn, "arms_body_length_ratio", text="Arms-Body Length Ratio")
                # Slider to adjust distance between legs
                row = post_process_box.row()
                row.prop(scn, "span_of_legs", text="Span of Two Legs")

                # Generate final pose string
                pose_string = f", {scn.pose_type}:"
                pose_string += f"{scn.head_body_height_ratio}:"
                pose_string += f"{scn.head_body_width_ratio}:"
                pose_string += f"{scn.legs_body_height_ratio}:"
                pose_string += f"{scn.arms_body_length_ratio}:"
                pose_string += f"{scn.span_of_legs}"
                # row = post_process_box.row()
                # Display final pose string
                # row.label(text=f"{pose_string}")

            if (
                scn.model_version == "v2.0-20240919"
                or scn.model_version == "v2.5-20250123"
            ):
                row = post_process_box.row()
                row.prop(
                    scn,
                    "show_advance_settings",
                    icon="HIDE_OFF" if scn.show_advance_settings else "HIDE_ON",
                    text="Advanced Settings",
                    emboss=False,
                )
                if scn.show_advance_settings:
                    row = post_process_box.row()
                    row.prop(scn, "texture", text="Texture")
                    row = post_process_box.row()
                    row.prop(scn, "pbr", text="PBR")
                    row = post_process_box.row()
                    row.prop(scn, "texture_seed", text="Texture Seed")
                    row = post_process_box.row()
                    row.prop(scn, "texture_alignment", text="Texture Alignment")
                    row = post_process_box.row()
                    row.prop(scn, "texture_quality", text="Texture Quality")
                    row = post_process_box.row()
                    row.prop(scn, "auto_size", text="Auto Size")
                    row = post_process_box.row()
                    row.prop(scn, "orientation", text="Orientation")

                    # layout.prop(scn, "blendermcp_port")

def _label_multiline(context, text, parent):
    chars = int(context.region.width / 11)  # 7 pix on 1 character
    wrapper = textwrap.TextWrapper(width=chars)
    text_lines = wrapper.wrap(text=text)
    for text_line in text_lines:
        parent.label(text=text_line)
import bpy
from .operators import DownloadTaskOperator, ResetPoseSettings
from .utils import calculate_generation_price

class SelectTaskOperator(bpy.types.Operator):
    bl_idname = "tripo3d.select_task"
    bl_label = "Select Task"
    bl_description = "Select this task"

    task_index: bpy.props.IntProperty()

    def execute(self, context):
        context.scene.tripo_task_index = self.task_index
        return {'FINISHED'}

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

        # Read task status stored in the scene
        for i, task in enumerate(scn.tripo_tasks):
            row = box.row()
            if i == scn.tripo_task_index:
                row.alert = True
            op = row.operator(
                "tripo3d.select_task",
                text=task.task_id,
                emboss=False,
                depress=(i == scn.tripo_task_index)
            )
            op.task_index = i
            if task.status == "running":
                row.prop(task, "progress", text=f"ETA {task.running_left_time} s", slider=True)
            elif task.status == "success":
                row.operator(
                    DownloadTaskOperator.bl_idname, text="Download"
                ).task_id = task.task_id
            else:
                row.label(text=task.status)
        box = layout.box()
        row = box.row()
        row.label(text="Add custom task:")
        row = box.row()
        row.prop(context.scene, "temp_taskid", text="")
        row.operator(
            DownloadTaskOperator.bl_idname, text="Search and add"
        ).task_id = scn.temp_taskid

        box = layout.box()
        index = context.scene.tripo_task_index
        if index < 0 or index >= len(context.scene.tripo_tasks):
            box.label(text="No task selected.")
            return

        task = context.scene.tripo_tasks[index]
        task.applier(box, context)


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
        row.operator("tripo3d.confirm_api_key", text="Confirm")

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
            mcp_box = layout.box()
            row = mcp_box.row(align=True)
            row.alignment = "CENTER"
            row.label(text="MCP Connections")
            row = mcp_box.row()
            row.prop(scn, "blendermcp_port")
            col = mcp_box.column(align=True)
            col.prop(scn, "blendermcp_use_polyhaven", text="Use assets from Poly Haven")

            sub_row = col.row()
            sub_row.enabled = False
            sub_row.prop(scn, "MCP_use_tripo", text="Use Tripo as assets generator")

            if not scn.blendermcp_server_running:
                mcp_box.operator("blendermcp.start_server", text="Start MCP Server")
            else:
                mcp_box.operator("blendermcp.stop_server", text="Stop MCP Server")
                mcp_box.label(text=f"Running on port {scn.blendermcp_port}")

            box = layout.box()
            row = box.row(align=True)  # Create a centered row layout
            row.alignment = "CENTER"
            row.label(text="Text_to_Model")
            col = box.column(align=True)
            col.label(text="Text prompts:")
            col.prop(context.scene, "text_prompts", text="")
            col.prop(scn, "enable_negative_prompts", text="Enable negative prompts")
            if scn.enable_negative_prompts:
                col.label(text="Negative prompts:")
                col.prop(context.scene, "negative_prompts", text="")
            row = col.row()
            row.prop(scn, "use_pose_control", text="Enable Pose Control")
            if scn.use_pose_control:
                row.operator(ResetPoseSettings.bl_idname, text="Reset Pose Control")

                col = box.column(align=True)
                # Dropdown to select T-pose or A-pose
                col.prop(scn, "pose_type", text="Pose Type")
                col = box.column(align=True)
                # Slider to adjust head-body height ratio
                col.prop(scn, "head_body_height_ratio", text="Head-Body Height Ratio")
                # Slider to adjust head-body width ratio
                col.prop(scn, "head_body_width_ratio", text="Head-Body Width Ratio")
                # Slider to adjust legs-body height ratio
                col.prop(scn, "legs_body_height_ratio", text="Legs-Body Height Ratio")
                # Slider to adjust arms-body length ratio
                col.prop(scn, "arms_body_length_ratio", text="Arms-Body Length Ratio")
                # Slider to adjust distance between legs
                col.prop(scn, "span_of_legs", text="Span of Two Legs")

            row = box.row()
            if not context.scene.text_prompts:
                row.enabled = False
            row.operator(
                "tripo3d.generate_text_model",
                text=f"Generate (cost:{calculate_generation_price(scn, 'text2model')})",
            )

            box = layout.box()
            row = box.row(align=True)
            row.alignment = "CENTER"
            row.label(text="Image_to_Model")

            if scn.model_version.startswith("v2.") and scn.multiview_generate_mode:
                row = box.row()
                row.operator(
                    "tripo3d.switch_image_mode", text="Switch to single image mode"
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
                    scn, "front_image", open="tripo3d.load_front_image"
                )

                # RIGHT IMAGE
                col_right = split.column(align=True)
                label_row = col_right.row()
                label_row.alignment = "CENTER"
                label_row.label(text="RIGHT")
                row = col_right.row()
                row.template_ID_preview(
                    scn, "right_image", open="tripo3d.load_right_image"
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
                    scn, "left_image", open="tripo3d.load_left_image"
                )

                # BACK IMAGE
                col_back = split.column(align=True)
                label_row = col_back.row()
                label_row.alignment = "CENTER"
                label_row.label(text="BACK")
                row = col_back.row()
                row.template_ID_preview(
                    scn, "back_image", open="tripo3d.load_back_image"
                )

                row = box.row()
                row.enabled = len(context.scene.front_image_path) > 0 and \
                              any([len(context.scene.left_image_path) > 0, \
                              len(context.scene.back_image_path) > 0, \
                              len(context.scene.right_image_path) > 0])
            else:
                row = box.row()
                row.operator(
                    "tripo3d.switch_image_mode", text="Switch to multiview mode"
                )
                row = box.row()
                row.template_ID_preview(
                    scn, "image", open="tripo3d.load_image"
                )
                row = box.row()
                row.label(text="Image Selected: ")
                row.label(text=scn.image_path)
                row = box.row()
                row.enabled = len(context.scene.image_path) > 0
            row.operator(
                "tripo3d.generate_image_model",
                text=f"Generate (cost:{calculate_generation_price(scn, 'image2model')})",
            )

            post_process_box = layout.box()
            row = post_process_box.row(align=True)
            row.alignment = "CENTER"
            row.label(text="Settings")

            col = post_process_box.column(align=True)
            row = col.row()
            row.label(text="Model Version")
            row.prop(context.scene, "model_version", text="")
            if scn.model_version.startswith("v2.") or scn.model_version.startswith("v3."):
                col.prop(scn, "quad", text="Enable quad mesh output")
                col.prop(scn, "use_custom_face_limit", text="Use custom face limit")

                row = post_process_box.row()
                row.prop(scn, "face_limit", text="Face Limit")
                row.enabled = scn.use_custom_face_limit

                row = post_process_box.row()
                if scn.multiview_generate_mode:
                    row.enabled = False
                row.prop(scn, "style", text="Style")

                row = post_process_box.row()
                row.prop(
                    scn,
                    "show_advance_settings",
                    icon="HIDE_OFF" if scn.show_advance_settings else "HIDE_ON",
                    text="Advanced Settings",
                    emboss=False,
                )
                if scn.show_advance_settings:
                    adv_col = post_process_box.column(align=True)
                    adv_col.prop(scn, "texture", text="Texture")
                    adv_col.prop(scn, "pbr", text="PBR")
                    adv_col.prop(scn, "texture_alignment", text="Texture Alignment")
                    adv_col.prop(scn, "texture_quality", text="Texture Quality")
                    if scn.model_version.startswith("v3."):
                        adv_col.prop(scn, "geometry_quality", text="Geometry Quality")
                    adv_col.prop(scn, "auto_size", text="Auto Size")
                    adv_col.prop(scn, "orientation", text="Orientation")

class TaskSubmittedMessageOperator(bpy.types.Operator):
    bl_idname = "tripo3d.task_submitted_message"
    bl_label = "Task Submitted Message"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    message: bpy.props.StringProperty(default="Task submitted, please check the task status in the Tripo Model Manager panel")
    
    def execute(self, context):
        return {'FINISHED'}
    
    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_popup(self, width=300)
    
    def draw(self, context):
        layout = self.layout
        layout.label(text=self.message)
        layout.label(text="Please switch to the Tripo Model Manager panel to view the task status")

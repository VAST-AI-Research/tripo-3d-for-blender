import bpy
from .utils import ui_update

class TaskPropertyGroup(bpy.types.PropertyGroup):
    task_id: bpy.props.StringProperty(default="")
    status: bpy.props.StringProperty(default="not initialized")
    task_type: bpy.props.StringProperty(default="")
    prompt: bpy.props.StringProperty(default="")
    progress: bpy.props.IntProperty(default=0, min=0, max=100,update=ui_update)
    input_image: bpy.props.PointerProperty(type=bpy.types.Image)
    input_image_path: bpy.props.StringProperty(default="")
    create_time: bpy.props.StringProperty(default="")
    render_image: bpy.props.PointerProperty(type=bpy.types.Image)
    running_left_time: bpy.props.FloatProperty(default=-1)

    def init(self, task_id: str, task_type: str="", input_image: bpy.types.Image=None, prompt: str=""):
        if not self.create_time:
            import datetime
            self.create_time = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        self.task_id = task_id
        self.task_type = task_type
        self.input_image = input_image
        self.prompt = prompt
        self.render_image = None

    def update(self, status: str=None, progress: int=None, render_image: bpy.types.Image = None, running_left_time: float=None):
        if status is not None:
            self.status = status
        if progress is not None:
            self.progress = progress
        if render_image is not None:
            self.render_image = render_image
        if running_left_time is not None:
            self.running_left_time = running_left_time

    def applier(self, layout, context):
        col = layout.column(align=True)
        col.label(text="Task Info: ")
        col.label(text="Task ID: " + self.task_id)
        if self.task_type:
            col.label(text="Task Type: " + self.task_type)
        if self.create_time:
            col.label(text="Create Time: " + self.create_time)
        if self.prompt:
            col.label(text="Prompt: " + self.prompt)
        if self.input_image:
            col.label(text="Input Image: " + self.input_image_path)
            col.template_ID_preview(self, "input_image", hide_buttons=True)
        if self.render_image:
            col.label(text="Rendered Image:")
            col.template_ID_preview(self, "render_image", hide_buttons=True)

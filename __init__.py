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
import requests
import os
import asyncio
import json
import threading
import tempfile
import logging
from functools import lru_cache, wraps
import time
import textwrap
import socket
import time
from bpy.props import StringProperty, IntProperty

import traceback
import shutil


def setup_logger():
    logger = logging.getLogger("tripo_addon")
    logger.setLevel(logging.INFO)

    # Get the addon's directory path
    addon_dir = os.path.dirname(os.path.realpath(__file__))
    log_file = os.path.join(addon_dir, "tripo_addon.log")

    try:
        # File handler
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

    except PermissionError:
        # If we can't create a log file, just use console logging
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        print("Warning: Could not create log file. Logging to console only.")

    return logger


logger = setup_logger()


class TripoConfig:
    API_BASE_URL = "https://api.tripo3d.ai/v2/openapi"
    TASK_ENDPOINT = f"{API_BASE_URL}/task"
    BALANCE_ENDPOINT = f"{API_BASE_URL}/user/balance"
    UPLOAD_ENDPOINT = f"{API_BASE_URL}/upload"
    MODEL_ENDPOINT = f"{API_BASE_URL}/model"  # Added for model-related operations

    # Task types according to documentation
    TASK_TYPES = {
        "TEXT_TO_MODEL": "text_to_model",
        "IMAGE_TO_MODEL": "image_to_model",
        "MULTIVIEW_TO_MODEL": "multiview_to_model",
        "ANIMATION": "animation",  # Added animation task type
        "POST_PROCESS": "post_process",  # Added post-process task type
    }

    # Model versions
    MODEL_VERSIONS = {"V1": "v1.0", "V2": "v2.0-20240919"}

    # Model styles
    MODEL_STYLES = {
        "ORIGINAL": "original",
        "CARTOON": "cartoon",
        "REALISTIC": "realistic",
    }

    # Animation types
    ANIMATION_TYPES = {"WALK": "walk", "RUN": "run", "IDLE": "idle", "DANCE": "dance"}

    # Status codes
    STATUS_CODES = {
        "QUEUED": "queued",
        "RUNNING": "running",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "SUCCESS": "success",  # Add success status
    }

    DEFAULT_TIMEOUT = 30  # seconds
    MAX_RETRIES = 3
    POLLING_INTERVAL = 2  # seconds

    # Add supported file types
    SUPPORTED_FILE_TYPES = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes

    @classmethod
    def get_task_url(cls, task_id=None):
        if task_id:
            return f"{cls.TASK_ENDPOINT}/{task_id}"
        return cls.TASK_ENDPOINT

    @classmethod
    def get_balance_url(cls):
        return cls.BALANCE_ENDPOINT


class TripoSettings(bpy.types.PropertyGroup):
    api_key: bpy.props.StringProperty(
        name="API Key",
        description="API Key for Tripo 3D",
        default="",
        subtype="PASSWORD",
    )
    api_key_confirmed: bpy.props.BoolProperty(name="API Key Confirmed", default=False)
    user_balance: bpy.props.StringProperty(name="User Balance", default="----")


class BlenderMCPServer:
    def __init__(self, host="localhost", port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.client = None
        self.command_queue = []
        self.buffer = b""  # Add buffer for incomplete data

    def start(self):
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.socket.setblocking(False)
            # Register the timer
            bpy.app.timers.register(self._process_server, persistent=True)
            print(f"BlenderMCP server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start server: {str(e)}")
            self.stop()

    def stop(self):
        self.running = False
        if hasattr(bpy.app.timers, "unregister"):
            if bpy.app.timers.is_registered(self._process_server):
                bpy.app.timers.unregister(self._process_server)
        if self.socket:
            self.socket.close()
        if self.client:
            self.client.close()
        self.socket = None
        self.client = None
        print("BlenderMCP server stopped")

    def _process_server(self):
        """Timer callback to process server operations"""
        if not self.running:
            return None  # Unregister timer

        try:
            # Accept new connections
            if not self.client and self.socket:
                try:
                    self.client, address = self.socket.accept()
                    self.client.setblocking(False)
                    print(f"Connected to client: {address}")
                except BlockingIOError:
                    pass  # No connection waiting
                except Exception as e:
                    print(f"Error accepting connection: {str(e)}")

            # Process existing connection
            if self.client:
                try:
                    # Try to receive data
                    try:
                        data = self.client.recv(8192)
                        if data:
                            self.buffer += data
                            # Try to process complete messages
                            try:
                                # Attempt to parse the buffer as JSON
                                command = json.loads(self.buffer.decode("utf-8"))
                                # If successful, clear the buffer and process command
                                self.buffer = b""
                                response = self.execute_command(command)
                                response_json = json.dumps(response)
                                self.client.sendall(response_json.encode("utf-8"))
                            except json.JSONDecodeError:
                                # Incomplete data, keep in buffer
                                pass
                        else:
                            # Connection closed by client
                            print("Client disconnected")
                            self.client.close()
                            self.client = None
                            self.buffer = b""
                    except BlockingIOError:
                        pass  # No data available
                    except Exception as e:
                        print(f"Error receiving data: {str(e)}")
                        self.client.close()
                        self.client = None
                        self.buffer = b""

                except Exception as e:
                    print(f"Error with client: {str(e)}")
                    if self.client:
                        self.client.close()
                        self.client = None
                    self.buffer = b""

        except Exception as e:
            print(f"Server error: {str(e)}")

        return 0.1  # Continue timer with 0.1 second interval

    def execute_command(self, command):
        """Execute a command in the main Blender thread"""
        try:
            cmd_type = command.get("type")
            params = command.get("params", {})

            # Ensure we're in the right context
            if cmd_type in ["create_object", "modify_object", "delete_object"]:
                override = bpy.context.copy()
                override["area"] = [
                    area for area in bpy.context.screen.areas if area.type == "VIEW_3D"
                ][0]
                with bpy.context.temp_override(**override):
                    return self._execute_command_internal(command)
            else:
                return self._execute_command_internal(command)

        except Exception as e:
            print(f"Error executing command: {str(e)}")

            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _execute_command_internal(self, command):
        """Internal command execution with proper context"""
        cmd_type = command.get("type")
        params = command.get("params", {})

        # Add a handler for checking PolyHaven status
        if cmd_type == "get_polyhaven_status":
            return {"status": "success", "result": self.get_polyhaven_status()}

        if cmd_type == "get_tripo_apikey":
            return {"status": "success", "result": self.get_tripo_apikey()}

        # Base handlers that are always available
        handlers = {
            "get_scene_info": self.get_scene_info,
            "create_object": self.create_object,
            "modify_object": self.modify_object,
            "delete_object": self.delete_object,
            "get_object_info": self.get_object_info,
            "execute_code": self.execute_code,
            "set_material": self.set_material,
            "get_polyhaven_status": self.get_polyhaven_status,
            "get_tripo_apikey": self.get_tripo_apikey,
            "import_tripo_glb_model": self.import_tripo_glb_model,
        }

        # Add Polyhaven handlers only if enabled
        if bpy.context.scene.blendermcp_use_polyhaven:
            polyhaven_handlers = {
                "get_polyhaven_categories": self.get_polyhaven_categories,
                "search_polyhaven_assets": self.search_polyhaven_assets,
                "download_polyhaven_asset": self.download_polyhaven_asset,
                "set_texture": self.set_texture,
            }
            handlers.update(polyhaven_handlers)

        handler = handlers.get(cmd_type)
        if handler:
            try:
                print(f"Executing handler for {cmd_type}")
                result = handler(**params)
                print(f"Handler execution complete")
                return {"status": "success", "result": result}
            except Exception as e:
                print(f"Error in handler: {str(e)}")
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        else:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}

    def import_tripo_glb_model(self, url):
        response = requests.get(url)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
        temp_file.write(response.content)
        temp_file.close()

        # Ensure we're in object mode before import
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.import_scene.gltf(filepath=temp_file.name)
        imported_objects = bpy.context.selected_objects
        model_info = []

        for obj in imported_objects:
            # 先设置旋转模式为欧拉XYZ
            obj.rotation_mode = 'XYZ'
            # 再旋转到面向+Y方向
            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians
            
            # 计算包围盒尺寸
            bbox_dimensions = [
                dim * scale for dim, scale in zip(obj.dimensions, obj.scale)
            ]

            model_info.append(
                {
                    "name": obj.name,
                    "dimensions": {
                        "x": round(bbox_dimensions[0], 4),
                        "y": round(bbox_dimensions[1], 4),
                        "z": round(bbox_dimensions[2], 4),
                    },
                }
            )

        os.unlink(temp_file.name)

        return {
            "status": "success",
            "message": "Model imported successfully",
            "models": model_info,
        }

    def get_simple_info(self):
        """Get basic Blender information"""
        return {
            "blender_version": ".".join(str(v) for v in bpy.app.version),
            "scene_name": bpy.context.scene.name,
            "object_count": len(bpy.context.scene.objects),
        }

    def get_scene_info(self):
        """Get information about the current Blender scene"""
        try:
            print("Getting scene info...")
            # Simplify the scene info to reduce data size
            scene_info = {
                "name": bpy.context.scene.name,
                "object_count": len(bpy.context.scene.objects),
                "objects": [],
                "materials_count": len(bpy.data.materials),
            }

            # Collect minimal object information (limit to first 10 objects)
            for i, obj in enumerate(bpy.context.scene.objects):
                if i >= 10:  # Reduced from 20 to 10
                    break

                obj_info = {
                    "name": obj.name,
                    "type": obj.type,
                    # Only include basic location data
                    "location": [
                        round(float(obj.location.x), 2),
                        round(float(obj.location.y), 2),
                        round(float(obj.location.z), 2),
                    ],
                }
                scene_info["objects"].append(obj_info)

            print(f"Scene info collected: {len(scene_info['objects'])} objects")
            return scene_info
        except Exception as e:
            print(f"Error in get_scene_info: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    def create_object(
        self,
        type="CUBE",
        name=None,
        location=(0, 0, 0),
        rotation=(0, 0, 0),
        scale=(1, 1, 1),
    ):
        """Create a new object in the scene"""
        # Deselect all objects
        bpy.ops.object.select_all(action="DESELECT")

        # Create the object based on type
        if type == "CUBE":
            bpy.ops.mesh.primitive_cube_add(
                location=location, rotation=rotation, scale=scale
            )
        elif type == "SPHERE":
            bpy.ops.mesh.primitive_uv_sphere_add(
                location=location, rotation=rotation, scale=scale
            )
        elif type == "CYLINDER":
            bpy.ops.mesh.primitive_cylinder_add(
                location=location, rotation=rotation, scale=scale
            )
        elif type == "PLANE":
            bpy.ops.mesh.primitive_plane_add(
                location=location, rotation=rotation, scale=scale
            )
        elif type == "CONE":
            bpy.ops.mesh.primitive_cone_add(
                location=location, rotation=rotation, scale=scale
            )
        elif type == "TORUS":
            bpy.ops.mesh.primitive_torus_add(
                location=location, rotation=rotation, scale=scale
            )
        elif type == "EMPTY":
            bpy.ops.object.empty_add(location=location, rotation=rotation, scale=scale)
        elif type == "CAMERA":
            bpy.ops.object.camera_add(location=location, rotation=rotation)
        elif type == "LIGHT":
            bpy.ops.object.light_add(
                type="POINT", location=location, rotation=rotation, scale=scale
            )
        else:
            raise ValueError(f"Unsupported object type: {type}")

        # Get the created object
        obj = bpy.context.active_object

        # Rename if name is provided
        if name:
            obj.name = name

        return {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [
                obj.rotation_euler.x,
                obj.rotation_euler.y,
                obj.rotation_euler.z,
            ],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
        }

    def modify_object(
        self, name, location=None, rotation=None, scale=None, visible=None
    ):
        """Modify an existing object in the scene"""
        # Find the object by name
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object not found: {name}")

        # Modify properties as requested
        if location is not None:
            obj.location = location

        if rotation is not None:
            obj.rotation_euler = rotation

        if scale is not None:
            obj.scale = scale

        if visible is not None:
            obj.hide_viewport = not visible
            obj.hide_render = not visible

        return {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [
                obj.rotation_euler.x,
                obj.rotation_euler.y,
                obj.rotation_euler.z,
            ],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            "visible": obj.visible_get(),
        }

    def delete_object(self, name):
        """Delete an object from the scene"""
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object not found: {name}")

        # Store the name to return
        obj_name = obj.name

        # Select and delete the object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.ops.object.delete()

        return {"deleted": obj_name}

    def get_object_info(self, name):
        """Get detailed information about a specific object"""
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object not found: {name}")

        # Basic object info
        obj_info = {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [
                obj.rotation_euler.x,
                obj.rotation_euler.y,
                obj.rotation_euler.z,
            ],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            "visible": obj.visible_get(),
            "materials": [],
        }

        # Add material slots
        for slot in obj.material_slots:
            if slot.material:
                obj_info["materials"].append(slot.material.name)

        # Add mesh data if applicable
        if obj.type == "MESH" and obj.data:
            mesh = obj.data
            obj_info["mesh"] = {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "polygons": len(mesh.polygons),
            }

        return obj_info

    def execute_code(self, code):
        """Execute arbitrary Blender Python code"""
        # This is powerful but potentially dangerous - use with caution
        try:
            # Create a local namespace for execution
            namespace = {"bpy": bpy}
            exec(code, namespace)
            return {"executed": True}
        except Exception as e:
            raise Exception(f"Code execution error: {str(e)}")

    def set_material(
        self, object_name, material_name=None, create_if_missing=True, color=None
    ):
        """Set or create a material for an object"""
        try:
            # Get the object
            obj = bpy.data.objects.get(object_name)
            if not obj:
                raise ValueError(f"Object not found: {object_name}")

            # Make sure object can accept materials
            if not hasattr(obj, "data") or not hasattr(obj.data, "materials"):
                raise ValueError(f"Object {object_name} cannot accept materials")

            # Create or get material
            if material_name:
                mat = bpy.data.materials.get(material_name)
                if not mat and create_if_missing:
                    mat = bpy.data.materials.new(name=material_name)
                    print(f"Created new material: {material_name}")
            else:
                # Generate unique material name if none provided
                mat_name = f"{object_name}_material"
                mat = bpy.data.materials.get(mat_name)
                if not mat:
                    mat = bpy.data.materials.new(name=mat_name)
                material_name = mat_name
                print(f"Using material: {mat_name}")

            # Set up material nodes if needed
            if mat:
                if not mat.use_nodes:
                    mat.use_nodes = True

                # Get or create Principled BSDF
                principled = mat.node_tree.nodes.get("Principled BSDF")
                if not principled:
                    principled = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
                    # Get or create Material Output
                    output = mat.node_tree.nodes.get("Material Output")
                    if not output:
                        output = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
                    # Link if not already linked
                    if not principled.outputs[0].links:
                        mat.node_tree.links.new(principled.outputs[0], output.inputs[0])

                # Set color if provided
                if color and len(color) >= 3:
                    principled.inputs["Base Color"].default_value = (
                        color[0],
                        color[1],
                        color[2],
                        1.0 if len(color) < 4 else color[3],
                    )
                    print(f"Set material color to {color}")

            # Assign material to object if not already assigned
            if mat:
                if not obj.data.materials:
                    obj.data.materials.append(mat)
                else:
                    # Only modify first material slot
                    obj.data.materials[0] = mat

                print(f"Assigned material {mat.name} to object {object_name}")

                return {
                    "status": "success",
                    "object": object_name,
                    "material": mat.name,
                    "color": color if color else None,
                }
            else:
                raise ValueError(f"Failed to create or find material: {material_name}")

        except Exception as e:
            print(f"Error in set_material: {str(e)}")
            traceback.print_exc()
            return {
                "status": "error",
                "message": str(e),
                "object": object_name,
                "material": material_name if "material_name" in locals() else None,
            }

    def render_scene(self, output_path=None, resolution_x=None, resolution_y=None):
        """Render the current scene"""
        if resolution_x is not None:
            bpy.context.scene.render.resolution_x = resolution_x

        if resolution_y is not None:
            bpy.context.scene.render.resolution_y = resolution_y

        if output_path:
            bpy.context.scene.render.filepath = output_path

        # Render the scene
        bpy.ops.render.render(write_still=bool(output_path))

        return {
            "rendered": True,
            "output_path": output_path if output_path else "[not saved]",
            "resolution": [
                bpy.context.scene.render.resolution_x,
                bpy.context.scene.render.resolution_y,
            ],
        }

    def get_polyhaven_categories(self, asset_type):
        """Get categories for a specific asset type from Polyhaven"""
        try:
            if asset_type not in ["hdris", "textures", "models", "all"]:
                return {
                    "error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"
                }

            response = requests.get(
                f"https://api.polyhaven.com/categories/{asset_type}"
            )
            if response.status_code == 200:
                return {"categories": response.json()}
            else:
                return {
                    "error": f"API request failed with status code {response.status_code}"
                }
        except Exception as e:
            return {"error": str(e)}

    def search_polyhaven_assets(self, asset_type=None, categories=None):
        """Search for assets from Polyhaven with optional filtering"""
        try:
            url = "https://api.polyhaven.com/assets"
            params = {}

            if asset_type and asset_type != "all":
                if asset_type not in ["hdris", "textures", "models"]:
                    return {
                        "error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"
                    }
                params["type"] = asset_type

            if categories:
                params["categories"] = categories

            response = requests.get(url, params=params)
            if response.status_code == 200:
                # Limit the response size to avoid overwhelming Blender
                assets = response.json()
                # Return only the first 20 assets to keep response size manageable
                limited_assets = {}
                for i, (key, value) in enumerate(assets.items()):
                    if i >= 20:  # Limit to 20 assets
                        break
                    limited_assets[key] = value

                return {
                    "assets": limited_assets,
                    "total_count": len(assets),
                    "returned_count": len(limited_assets),
                }
            else:
                return {
                    "error": f"API request failed with status code {response.status_code}"
                }
        except Exception as e:
            return {"error": str(e)}

    def download_polyhaven_asset(
        self, asset_id, asset_type, resolution="1k", file_format=None
    ):
        try:
            # First get the files information
            files_response = requests.get(f"https://api.polyhaven.com/files/{asset_id}")
            if files_response.status_code != 200:
                return {
                    "error": f"Failed to get asset files: {files_response.status_code}"
                }

            files_data = files_response.json()

            # Handle different asset types
            if asset_type == "hdris":
                # For HDRIs, download the .hdr or .exr file
                if not file_format:
                    file_format = "hdr"  # Default format for HDRIs

                if (
                    "hdri" in files_data
                    and resolution in files_data["hdri"]
                    and file_format in files_data["hdri"][resolution]
                ):
                    file_info = files_data["hdri"][resolution][file_format]
                    file_url = file_info["url"]

                    # For HDRIs, we need to save to a temporary file first
                    # since Blender can't properly load HDR data directly from memory
                    with tempfile.NamedTemporaryFile(
                        suffix=f".{file_format}", delete=False
                    ) as tmp_file:
                        # Download the file
                        response = requests.get(file_url)
                        if response.status_code != 200:
                            return {
                                "error": f"Failed to download HDRI: {response.status_code}"
                            }

                        tmp_file.write(response.content)
                        tmp_path = tmp_file.name

                    try:
                        # Create a new world if none exists
                        if not bpy.data.worlds:
                            bpy.data.worlds.new("World")

                        world = bpy.data.worlds[0]
                        world.use_nodes = True
                        node_tree = world.node_tree

                        # Clear existing nodes
                        for node in node_tree.nodes:
                            node_tree.nodes.remove(node)

                        # Create nodes
                        tex_coord = node_tree.nodes.new(type="ShaderNodeTexCoord")
                        tex_coord.location = (-800, 0)

                        mapping = node_tree.nodes.new(type="ShaderNodeMapping")
                        mapping.location = (-600, 0)

                        # Load the image from the temporary file
                        env_tex = node_tree.nodes.new(type="ShaderNodeTexEnvironment")
                        env_tex.location = (-400, 0)
                        env_tex.image = bpy.data.images.load(tmp_path)

                        # FIXED: Use a color space that exists in all Blender versions
                        if file_format.lower() == "exr":
                            # Try to use Linear color space for EXR files
                            try:
                                env_tex.image.colorspace_settings.name = "Linear"
                            except:
                                # Fallback to Non-Color if Linear isn't available
                                env_tex.image.colorspace_settings.name = "Non-Color"
                        else:  # hdr
                            # For HDR files, try these options in order
                            for color_space in [
                                "Linear",
                                "Linear Rec.709",
                                "Non-Color",
                            ]:
                                try:
                                    env_tex.image.colorspace_settings.name = color_space
                                    break  # Stop if we successfully set a color space
                                except:
                                    continue

                        background = node_tree.nodes.new(type="ShaderNodeBackground")
                        background.location = (-200, 0)

                        output = node_tree.nodes.new(type="ShaderNodeOutputWorld")
                        output.location = (0, 0)

                        # Connect nodes
                        node_tree.links.new(
                            tex_coord.outputs["Generated"], mapping.inputs["Vector"]
                        )
                        node_tree.links.new(
                            mapping.outputs["Vector"], env_tex.inputs["Vector"]
                        )
                        node_tree.links.new(
                            env_tex.outputs["Color"], background.inputs["Color"]
                        )
                        node_tree.links.new(
                            background.outputs["Background"], output.inputs["Surface"]
                        )

                        # Set as active world
                        bpy.context.scene.world = world

                        # Clean up temporary file
                        try:
                            tempfile._cleanup()  # This will clean up all temporary files
                        except:
                            pass

                        return {
                            "success": True,
                            "message": f"HDRI {asset_id} imported successfully",
                            "image_name": env_tex.image.name,
                        }
                    except Exception as e:
                        return {"error": f"Failed to set up HDRI in Blender: {str(e)}"}
                else:
                    return {
                        "error": f"Requested resolution or format not available for this HDRI"
                    }

            elif asset_type == "textures":
                if not file_format:
                    file_format = "jpg"  # Default format for textures

                downloaded_maps = {}

                try:
                    for map_type in files_data:
                        if map_type not in ["blend", "gltf"]:  # Skip non-texture files
                            if (
                                resolution in files_data[map_type]
                                and file_format in files_data[map_type][resolution]
                            ):
                                file_info = files_data[map_type][resolution][
                                    file_format
                                ]
                                file_url = file_info["url"]

                                # Use NamedTemporaryFile like we do for HDRIs
                                with tempfile.NamedTemporaryFile(
                                    suffix=f".{file_format}", delete=False
                                ) as tmp_file:
                                    # Download the file
                                    response = requests.get(file_url)
                                    if response.status_code == 200:
                                        tmp_file.write(response.content)
                                        tmp_path = tmp_file.name

                                        # Load image from temporary file
                                        image = bpy.data.images.load(tmp_path)
                                        image.name = (
                                            f"{asset_id}_{map_type}.{file_format}"
                                        )

                                        # Pack the image into .blend file
                                        image.pack()

                                        # Set color space based on map type
                                        if map_type in ["color", "diffuse", "albedo"]:
                                            try:
                                                image.colorspace_settings.name = "sRGB"
                                            except:
                                                pass
                                        else:
                                            try:
                                                image.colorspace_settings.name = (
                                                    "Non-Color"
                                                )
                                            except:
                                                pass

                                        downloaded_maps[map_type] = image

                                        # Clean up temporary file
                                        try:
                                            os.unlink(tmp_path)
                                        except:
                                            pass

                    if not downloaded_maps:
                        return {
                            "error": f"No texture maps found for the requested resolution and format"
                        }

                    # Create a new material with the downloaded textures
                    mat = bpy.data.materials.new(name=asset_id)
                    mat.use_nodes = True
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links

                    # Clear default nodes
                    for node in nodes:
                        nodes.remove(node)

                    # Create output node
                    output = nodes.new(type="ShaderNodeOutputMaterial")
                    output.location = (300, 0)

                    # Create principled BSDF node
                    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
                    principled.location = (0, 0)
                    links.new(principled.outputs[0], output.inputs[0])

                    # Add texture nodes based on available maps
                    tex_coord = nodes.new(type="ShaderNodeTexCoord")
                    tex_coord.location = (-800, 0)

                    mapping = nodes.new(type="ShaderNodeMapping")
                    mapping.location = (-600, 0)
                    mapping.vector_type = (
                        "TEXTURE"  # Changed from default 'POINT' to 'TEXTURE'
                    )
                    links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])

                    # Position offset for texture nodes
                    x_pos = -400
                    y_pos = 300

                    # Connect different texture maps
                    for map_type, image in downloaded_maps.items():
                        tex_node = nodes.new(type="ShaderNodeTexImage")
                        tex_node.location = (x_pos, y_pos)
                        tex_node.image = image

                        # Set color space based on map type
                        if map_type.lower() in ["color", "diffuse", "albedo"]:
                            try:
                                tex_node.image.colorspace_settings.name = "sRGB"
                            except:
                                pass  # Use default if sRGB not available
                        else:
                            try:
                                tex_node.image.colorspace_settings.name = "Non-Color"
                            except:
                                pass  # Use default if Non-Color not available

                        links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

                        # Connect to appropriate input on Principled BSDF
                        if map_type.lower() in ["color", "diffuse", "albedo"]:
                            links.new(
                                tex_node.outputs["Color"],
                                principled.inputs["Base Color"],
                            )
                        elif map_type.lower() in ["roughness", "rough"]:
                            links.new(
                                tex_node.outputs["Color"],
                                principled.inputs["Roughness"],
                            )
                        elif map_type.lower() in ["metallic", "metalness", "metal"]:
                            links.new(
                                tex_node.outputs["Color"], principled.inputs["Metallic"]
                            )
                        elif map_type.lower() in ["normal", "nor"]:
                            # Add normal map node
                            normal_map = nodes.new(type="ShaderNodeNormalMap")
                            normal_map.location = (x_pos + 200, y_pos)
                            links.new(
                                tex_node.outputs["Color"], normal_map.inputs["Color"]
                            )
                            links.new(
                                normal_map.outputs["Normal"],
                                principled.inputs["Normal"],
                            )
                        elif map_type in ["displacement", "disp", "height"]:
                            # Add displacement node
                            disp_node = nodes.new(type="ShaderNodeDisplacement")
                            disp_node.location = (x_pos + 200, y_pos - 200)
                            links.new(
                                tex_node.outputs["Color"], disp_node.inputs["Height"]
                            )
                            links.new(
                                disp_node.outputs["Displacement"],
                                output.inputs["Displacement"],
                            )

                        y_pos -= 250

                    return {
                        "success": True,
                        "message": f"Texture {asset_id} imported as material",
                        "material": mat.name,
                        "maps": list(downloaded_maps.keys()),
                    }

                except Exception as e:
                    return {"error": f"Failed to process textures: {str(e)}"}

            elif asset_type == "models":
                # For models, prefer glTF format if available
                if not file_format:
                    file_format = "gltf"  # Default format for models

                if file_format in files_data and resolution in files_data[file_format]:
                    file_info = files_data[file_format][resolution][file_format]
                    file_url = file_info["url"]

                    # Create a temporary directory to store the model and its dependencies
                    temp_dir = tempfile.mkdtemp()
                    main_file_path = ""

                    try:
                        # Download the main model file
                        main_file_name = file_url.split("/")[-1]
                        main_file_path = os.path.join(temp_dir, main_file_name)

                        response = requests.get(file_url)
                        if response.status_code != 200:
                            return {
                                "error": f"Failed to download model: {response.status_code}"
                            }

                        with open(main_file_path, "wb") as f:
                            f.write(response.content)

                        # Check for included files and download them
                        if "include" in file_info and file_info["include"]:
                            for include_path, include_info in file_info[
                                "include"
                            ].items():
                                # Get the URL for the included file - this is the fix
                                include_url = include_info["url"]

                                # Create the directory structure for the included file
                                include_file_path = os.path.join(temp_dir, include_path)
                                os.makedirs(
                                    os.path.dirname(include_file_path), exist_ok=True
                                )

                                # Download the included file
                                include_response = requests.get(include_url)
                                if include_response.status_code == 200:
                                    with open(include_file_path, "wb") as f:
                                        f.write(include_response.content)
                                else:
                                    print(
                                        f"Failed to download included file: {include_path}"
                                    )

                        # Import the model into Blender
                        if file_format == "gltf" or file_format == "glb":
                            bpy.ops.import_scene.gltf(filepath=main_file_path)
                        elif file_format == "fbx":
                            bpy.ops.import_scene.fbx(filepath=main_file_path)
                        elif file_format == "obj":
                            bpy.ops.import_scene.obj(filepath=main_file_path)
                        elif file_format == "blend":
                            # For blend files, we need to append or link
                            with bpy.data.libraries.load(
                                main_file_path, link=False
                            ) as (data_from, data_to):
                                data_to.objects = data_from.objects

                            # Link the objects to the scene
                            for obj in data_to.objects:
                                if obj is not None:
                                    bpy.context.collection.objects.link(obj)
                        else:
                            return {"error": f"Unsupported model format: {file_format}"}

                        # Get the names of imported objects
                        imported_objects = [
                            obj.name for obj in bpy.context.selected_objects
                        ]

                        return {
                            "success": True,
                            "message": f"Model {asset_id} imported successfully",
                            "imported_objects": imported_objects,
                        }
                    except Exception as e:
                        return {"error": f"Failed to import model: {str(e)}"}
                    finally:
                        # Clean up temporary directory
                        try:
                            shutil.rmtree(temp_dir)
                        except:
                            print(f"Failed to clean up temporary directory: {temp_dir}")
                else:
                    return {
                        "error": f"Requested format or resolution not available for this model"
                    }

            else:
                return {"error": f"Unsupported asset type: {asset_type}"}

        except Exception as e:
            return {"error": f"Failed to download asset: {str(e)}"}

    def set_texture(self, object_name, texture_id):
        """Apply a previously downloaded Polyhaven texture to an object by creating a new material"""
        try:
            # Get the object
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}

            # Make sure object can accept materials
            if not hasattr(obj, "data") or not hasattr(obj.data, "materials"):
                return {"error": f"Object {object_name} cannot accept materials"}

            # Find all images related to this texture and ensure they're properly loaded
            texture_images = {}
            for img in bpy.data.images:
                if img.name.startswith(texture_id + "_"):
                    # Extract the map type from the image name
                    map_type = img.name.split("_")[-1].split(".")[0]

                    # Force a reload of the image
                    img.reload()

                    # Ensure proper color space
                    if map_type.lower() in ["color", "diffuse", "albedo"]:
                        try:
                            img.colorspace_settings.name = "sRGB"
                        except:
                            pass
                    else:
                        try:
                            img.colorspace_settings.name = "Non-Color"
                        except:
                            pass

                    # Ensure the image is packed
                    if not img.packed_file:
                        img.pack()

                    texture_images[map_type] = img
                    print(f"Loaded texture map: {map_type} - {img.name}")

                    # Debug info
                    print(f"Image size: {img.size[0]}x{img.size[1]}")
                    print(f"Color space: {img.colorspace_settings.name}")
                    print(f"File format: {img.file_format}")
                    print(f"Is packed: {bool(img.packed_file)}")

            if not texture_images:
                return {
                    "error": f"No texture images found for: {texture_id}. Please download the texture first."
                }

            # Create a new material
            new_mat_name = f"{texture_id}_material_{object_name}"

            # Remove any existing material with this name to avoid conflicts
            existing_mat = bpy.data.materials.get(new_mat_name)
            if existing_mat:
                bpy.data.materials.remove(existing_mat)

            new_mat = bpy.data.materials.new(name=new_mat_name)
            new_mat.use_nodes = True

            # Set up the material nodes
            nodes = new_mat.node_tree.nodes
            links = new_mat.node_tree.links

            # Clear default nodes
            nodes.clear()

            # Create output node
            output = nodes.new(type="ShaderNodeOutputMaterial")
            output.location = (600, 0)

            # Create principled BSDF node
            principled = nodes.new(type="ShaderNodeBsdfPrincipled")
            principled.location = (300, 0)
            links.new(principled.outputs[0], output.inputs[0])

            # Add texture nodes based on available maps
            tex_coord = nodes.new(type="ShaderNodeTexCoord")
            tex_coord.location = (-800, 0)

            mapping = nodes.new(type="ShaderNodeMapping")
            mapping.location = (-600, 0)
            mapping.vector_type = "TEXTURE"  # Changed from default 'POINT' to 'TEXTURE'
            links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])

            # Position offset for texture nodes
            x_pos = -400
            y_pos = 300

            # Connect different texture maps
            for map_type, image in texture_images.items():
                tex_node = nodes.new(type="ShaderNodeTexImage")
                tex_node.location = (x_pos, y_pos)
                tex_node.image = image

                # Set color space based on map type
                if map_type.lower() in ["color", "diffuse", "albedo"]:
                    try:
                        tex_node.image.colorspace_settings.name = "sRGB"
                    except:
                        pass  # Use default if sRGB not available
                else:
                    try:
                        tex_node.image.colorspace_settings.name = "Non-Color"
                    except:
                        pass  # Use default if Non-Color not available

                links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

                # Connect to appropriate input on Principled BSDF
                if map_type.lower() in ["color", "diffuse", "albedo"]:
                    links.new(
                        tex_node.outputs["Color"], principled.inputs["Base Color"]
                    )
                elif map_type.lower() in ["roughness", "rough"]:
                    links.new(tex_node.outputs["Color"], principled.inputs["Roughness"])
                elif map_type.lower() in ["metallic", "metalness", "metal"]:
                    links.new(tex_node.outputs["Color"], principled.inputs["Metallic"])
                elif map_type.lower() in ["normal", "nor", "dx", "gl"]:
                    # Add normal map node
                    normal_map = nodes.new(type="ShaderNodeNormalMap")
                    normal_map.location = (x_pos + 200, y_pos)
                    links.new(tex_node.outputs["Color"], normal_map.inputs["Color"])
                    links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
                elif map_type.lower() in ["displacement", "disp", "height"]:
                    # Add displacement node
                    disp_node = nodes.new(type="ShaderNodeDisplacement")
                    disp_node.location = (x_pos + 200, y_pos - 200)
                    disp_node.inputs[
                        "Scale"
                    ].default_value = 0.1  # Reduce displacement strength
                    links.new(tex_node.outputs["Color"], disp_node.inputs["Height"])
                    links.new(
                        disp_node.outputs["Displacement"], output.inputs["Displacement"]
                    )

                y_pos -= 250

            # Second pass: Connect nodes with proper handling for special cases
            texture_nodes = {}

            # First find all texture nodes and store them by map type
            for node in nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    for map_type, image in texture_images.items():
                        if node.image == image:
                            texture_nodes[map_type] = node
                            break

            # Now connect everything using the nodes instead of images
            # Handle base color (diffuse)
            for map_name in ["color", "diffuse", "albedo"]:
                if map_name in texture_nodes:
                    links.new(
                        texture_nodes[map_name].outputs["Color"],
                        principled.inputs["Base Color"],
                    )
                    print(f"Connected {map_name} to Base Color")
                    break

            # Handle roughness
            for map_name in ["roughness", "rough"]:
                if map_name in texture_nodes:
                    links.new(
                        texture_nodes[map_name].outputs["Color"],
                        principled.inputs["Roughness"],
                    )
                    print(f"Connected {map_name} to Roughness")
                    break

            # Handle metallic
            for map_name in ["metallic", "metalness", "metal"]:
                if map_name in texture_nodes:
                    links.new(
                        texture_nodes[map_name].outputs["Color"],
                        principled.inputs["Metallic"],
                    )
                    print(f"Connected {map_name} to Metallic")
                    break

            # Handle normal maps
            for map_name in ["gl", "dx", "nor"]:
                if map_name in texture_nodes:
                    normal_map_node = nodes.new(type="ShaderNodeNormalMap")
                    normal_map_node.location = (100, 100)
                    links.new(
                        texture_nodes[map_name].outputs["Color"],
                        normal_map_node.inputs["Color"],
                    )
                    links.new(
                        normal_map_node.outputs["Normal"], principled.inputs["Normal"]
                    )
                    print(f"Connected {map_name} to Normal")
                    break

            # Handle displacement
            for map_name in ["displacement", "disp", "height"]:
                if map_name in texture_nodes:
                    disp_node = nodes.new(type="ShaderNodeDisplacement")
                    disp_node.location = (300, -200)
                    disp_node.inputs[
                        "Scale"
                    ].default_value = 0.1  # Reduce displacement strength
                    links.new(
                        texture_nodes[map_name].outputs["Color"],
                        disp_node.inputs["Height"],
                    )
                    links.new(
                        disp_node.outputs["Displacement"], output.inputs["Displacement"]
                    )
                    print(f"Connected {map_name} to Displacement")
                    break

            # Handle ARM texture (Ambient Occlusion, Roughness, Metallic)
            if "arm" in texture_nodes:
                separate_rgb = nodes.new(type="ShaderNodeSeparateRGB")
                separate_rgb.location = (-200, -100)
                links.new(
                    texture_nodes["arm"].outputs["Color"], separate_rgb.inputs["Image"]
                )

                # Connect Roughness (G) if no dedicated roughness map
                if not any(
                    map_name in texture_nodes for map_name in ["roughness", "rough"]
                ):
                    links.new(separate_rgb.outputs["G"], principled.inputs["Roughness"])
                    print("Connected ARM.G to Roughness")

                # Connect Metallic (B) if no dedicated metallic map
                if not any(
                    map_name in texture_nodes
                    for map_name in ["metallic", "metalness", "metal"]
                ):
                    links.new(separate_rgb.outputs["B"], principled.inputs["Metallic"])
                    print("Connected ARM.B to Metallic")

                # For AO (R channel), multiply with base color if we have one
                base_color_node = None
                for map_name in ["color", "diffuse", "albedo"]:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type="ShaderNodeMixRGB")
                    mix_node.location = (100, 200)
                    mix_node.blend_type = "MULTIPLY"
                    mix_node.inputs["Fac"].default_value = 0.8  # 80% influence

                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs["Color"].links:
                        if link.to_socket == principled.inputs["Base Color"]:
                            links.remove(link)

                    # Connect through the mix node
                    links.new(base_color_node.outputs["Color"], mix_node.inputs[1])
                    links.new(separate_rgb.outputs["R"], mix_node.inputs[2])
                    links.new(
                        mix_node.outputs["Color"], principled.inputs["Base Color"]
                    )
                    print("Connected ARM.R to AO mix with Base Color")

            # Handle AO (Ambient Occlusion) if separate
            if "ao" in texture_nodes:
                base_color_node = None
                for map_name in ["color", "diffuse", "albedo"]:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type="ShaderNodeMixRGB")
                    mix_node.location = (100, 200)
                    mix_node.blend_type = "MULTIPLY"
                    mix_node.inputs["Fac"].default_value = 0.8  # 80% influence

                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs["Color"].links:
                        if link.to_socket == principled.inputs["Base Color"]:
                            links.remove(link)

                    # Connect through the mix node
                    links.new(base_color_node.outputs["Color"], mix_node.inputs[1])
                    links.new(texture_nodes["ao"].outputs["Color"], mix_node.inputs[2])
                    links.new(
                        mix_node.outputs["Color"], principled.inputs["Base Color"]
                    )
                    print("Connected AO to mix with Base Color")

            # CRITICAL: Make sure to clear all existing materials from the object
            while len(obj.data.materials) > 0:
                obj.data.materials.pop(index=0)

            # Assign the new material to the object
            obj.data.materials.append(new_mat)

            # CRITICAL: Make the object active and select it
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            # CRITICAL: Force Blender to update the material
            bpy.context.view_layer.update()

            # Get the list of texture maps
            texture_maps = list(texture_images.keys())

            # Get info about texture nodes for debugging
            material_info = {
                "name": new_mat.name,
                "has_nodes": new_mat.use_nodes,
                "node_count": len(new_mat.node_tree.nodes),
                "texture_nodes": [],
            }

            for node in new_mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    connections = []
                    for output in node.outputs:
                        for link in output.links:
                            connections.append(
                                f"{output.name} → {link.to_node.name}.{link.to_socket.name}"
                            )

                    material_info["texture_nodes"].append(
                        {
                            "name": node.name,
                            "image": node.image.name,
                            "colorspace": node.image.colorspace_settings.name,
                            "connections": connections,
                        }
                    )

            return {
                "success": True,
                "message": f"Created new material and applied texture {texture_id} to {object_name}",
                "material": new_mat.name,
                "maps": texture_maps,
                "material_info": material_info,
            }

        except Exception as e:
            print(f"Error in set_texture: {str(e)}")
            traceback.print_exc()
            return {"error": f"Failed to apply texture: {str(e)}"}

    def get_polyhaven_status(self):
        """Get the current status of PolyHaven integration"""
        enabled = bpy.context.scene.blendermcp_use_polyhaven
        if enabled:
            return {
                "enabled": True,
                "message": "PolyHaven integration is enabled and ready to use.",
            }
        else:
            return {
                "enabled": False,
                "message": """PolyHaven integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use assets from Poly Haven' checkbox
                            3. Restart the connection to Claude""",
            }

    def get_tripo_apikey(self):
        """获取当前Tripo API密钥状态"""
        api_key = bpy.context.scene.api_key
        print(
            "api_key: ",
            api_key,
            "API密钥已配置" if api_key else "未找到API密钥，请前往插件面板配置",
        )
        return {
            "configured": bool(api_key),
            "api_key": api_key,
            "message": "API密钥已配置"
            if api_key
            else "未找到API密钥，请前往插件面板配置",
        }


def ui_update(self, context):
    if not context.area or context.area.type != "VIEW_3D":
        return None

    # Store last update time to prevent too frequent updates
    current_time = time.time()
    last_update = context.scene.last_ui_update

    # Only update if more than 0.1 seconds have passed
    if current_time - last_update > 0.1:
        for region in context.area.regions:
            if region.type == "UI":
                region.tag_redraw()
        context.scene.last_ui_update = current_time

    return None


def retry_with_backoff(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = TripoConfig.MAX_RETRIES
        retry_delay = 1  # Start with 1 second delay

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.RequestException, TripoAPIError) as e:
                if attempt == max_retries - 1:  # Last attempt
                    raise  # Re-raise the last error

                logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

    return wrapper


@retry_with_backoff
def fetch_data(url, headers_tuple, method="GET", data=None, files=None):
    headers = dict([headers_tuple[i : i + 2] for i in range(0, len(headers_tuple), 2)])
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            if files:
                response = requests.post(url, headers=headers, files=files)
            elif data:
                response = requests.post(url, headers=headers, json=data)
            else:
                response = requests.post(url, headers=headers)

        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Failed to fetch data: {response.status_code}")
            raise Exception(f"API Error: Received response code {response.status_code}")
    except requests.RequestException as e:
        logging.error(f"Network Error: {str(e)}")
        raise


def upload_file(url, headers_tuple, file_path):
    """
    Upload a file to Tripo API

    Args:
        url: Upload endpoint URL
        headers_tuple: Authorization headers
        file_path: Path to the file to upload

    Returns:
        dict: Response from the API containing file_token
    """
    headers = dict([headers_tuple[i : i + 2] for i in range(0, len(headers_tuple), 2)])

    # Validate file exists
    if not os.path.exists(file_path):
        raise TripoValidationError(f"File not found: {file_path}")

    # Validate file size
    file_size = os.path.getsize(file_path)
    if file_size > TripoConfig.MAX_FILE_SIZE:
        raise TripoValidationError(
            f"File size ({file_size} bytes) exceeds maximum allowed size ({TripoConfig.MAX_FILE_SIZE} bytes)"
        )

    # Get file extension and validate type
    file_ext = os.path.splitext(file_path)[1][1:].lower()
    if file_ext not in TripoConfig.SUPPORTED_FILE_TYPES:
        raise TripoValidationError(
            f"Unsupported file type: {file_ext}. Supported types: {', '.join(TripoConfig.SUPPORTED_FILE_TYPES.keys())}"
        )

    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (
                    os.path.basename(file_path),
                    f,
                    TripoConfig.SUPPORTED_FILE_TYPES[file_ext],
                )
            }
            response = requests.post(url, headers=headers, files=files)

        if response.status_code == 200:
            return response.json()
        else:
            raise TripoAPIError.from_response(response)

    except requests.RequestException as e:
        raise TripoNetworkError(f"Failed to upload file: {str(e)}")


class ProgressTracker:
    def __init__(self, context, is_text_generating=True):
        self.context = context
        self.is_text_generating = is_text_generating
        self.start_time = time.time()

    def __enter__(self):
        if self.is_text_generating:
            self.context.scene.text_model_generating = True
        else:
            self.context.scene.image_model_generating = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_text_generating:
            self.context.scene.text_model_generating = False
            self.context.scene.text_generating_percentage = 0
        else:
            self.context.scene.image_model_generating = False
            self.context.scene.image_generating_percentage = 0

    def update_progress(self, progress, status=None):
        if self.is_text_generating:
            self.context.scene.text_generating_percentage = progress
        else:
            self.context.scene.image_generating_percentage = progress

        if status and hasattr(self.context.scene, "generation_status"):
            self.context.scene.generation_status = status

        if hasattr(self.context.scene, "generation_elapsed_time"):
            elapsed_time = time.time() - self.start_time
            self.context.scene.generation_elapsed_time = elapsed_time


async def receive_one(tid, context, isTextGenerating):
    progress_tracker = ProgressTracker(context, isTextGenerating)

    try:
        with progress_tracker:
            while True:
                base_url = f"{TripoConfig.TASK_ENDPOINT}/{tid}"
                headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")
                data = fetch_data(base_url, headers_tuple)

                status = data.get("data", {}).get("status")
                progress_value = float(data["data"]["progress"])

                progress_tracker.update_progress(
                    progress_value, f"Task {status}: {progress_value}%"
                )
                scn = context.scene
                task_status_array = scn.task_status_array

                # 标记是否找到任务
                task_found = False

                for task in task_status_array:
                    if task.task_id == tid:  # 使用 task.task_id 访问
                        task.status = status  # 更新状态
                        task_found = True
                        break

                if not task_found:
                    # 如果任务未找到，添加新任务
                    new_task = task_status_array.add()
                    new_task.task_id = tid  # 设置任务 ID
                    new_task.status = status  # 设置任务状态

                if status in [
                    TripoConfig.STATUS_CODES["COMPLETED"],
                    TripoConfig.STATUS_CODES["SUCCESS"],
                ]:
                    Update_User_balance(context.scene.api_key, context)
                    return data
                elif status == TripoConfig.STATUS_CODES["FAILED"]:
                    raise TripoAPIError(
                        f"Task failed: {data.get('data', {}).get('message', 'Unknown error')}"
                    )
                elif status not in [
                    TripoConfig.STATUS_CODES["RUNNING"],
                    TripoConfig.STATUS_CODES["QUEUED"],
                ]:
                    raise TripoAPIError(f"Unknown task status: {status}")

                await asyncio.sleep(TripoConfig.POLLING_INTERVAL)

    except Exception as e:
        logging.error(f"Error in receive_one: {str(e)}")
        raise


def show_error_dialog(error_message):
    def draw(self, context):
        self.layout.label(text=error_message)

    def show_message():
        bpy.context.window_manager.popup_menu(draw, title="Error", icon="ERROR")

    # Schedule the dialog to be shown in the main thread
    bpy.app.timers.register(show_message, first_interval=0.1)


async def search_task(tid, context, isTextGenerating):
    try:
        result = await receive_one(tid, context, isTextGenerating)
        print(result["data"])

        # Extract model URL based on response structure
        glb_model_url = None
        model_type = None
        result_data = result["data"].get("result", {})

        # 按优先级检查三个可能的模型字段
        model_fields = ["pbr_model", "base_model", "model"]

        if result["data"]["input"]["model_version"] in [
            "v2.0-20240919",
            "v2.5-20250123",
        ]:
            # 新版优先检查 pbr_model -> base_model -> model
            for field in model_fields:
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break
        else:
            # 旧版检查顺序 model -> base_model -> pbr_model
            for field in reversed(model_fields):
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break

        if not glb_model_url:
            raise TripoAPIError(
                "No model URL found in response (checked pbr_model/base_model/model)"
            )
        if isTextGenerating:
            context.scene.text_is_importing_model = True
        else:
            context.scene.image_is_importing_model = True
        await gltf_model_download(glb_model_url, context, isTextGenerating, model_type)

        # Reset states
        if isTextGenerating:
            context.scene.text_model_generating = False
            context.scene.text_generating_percentage = 0
        else:
            context.scene.image_model_generating = False
            context.scene.image_generating_percentage = 0

    except Exception as e:
        error_message = f"Error during task search: {str(e)}. Please check the response or contact support."
        show_error_dialog(error_message)
        # Reset states
        if isTextGenerating:
            context.scene.text_model_generating = False
            context.scene.text_generating_percentage = 0
        else:
            context.scene.image_model_generating = False
            context.scene.image_generating_percentage = 0


async def manager_receive_one(tid, context):
    try:
        scn = context.scene
        while True:
            base_url = f"{TripoConfig.TASK_ENDPOINT}/{tid}"
            headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")
            data = fetch_data(base_url, headers_tuple)
            status = data.get("data", {}).get("status")
            task_status_array = scn.task_status_array

            # 标记是否找到任务
            task_found = False

            for task in task_status_array:
                if task.task_id == tid:  # 使用 task.task_id 访问
                    task.status = status  # 更新状态
                    task_found = True
                    break

            if not task_found:
                # 如果任务未找到，添加新任务
                new_task = task_status_array.add()
                new_task.task_id = tid  # 设置任务 ID
                new_task.status = status  # 设置任务状态

            if status in [
                TripoConfig.STATUS_CODES["COMPLETED"],
                TripoConfig.STATUS_CODES["SUCCESS"],
            ]:
                Update_User_balance(context.scene.api_key, context)
                return data
            elif status == TripoConfig.STATUS_CODES["FAILED"]:
                raise TripoAPIError(
                    f"Task failed: {data.get('data', {}).get('message', 'Unknown error')}"
                )
            elif status not in [
                TripoConfig.STATUS_CODES["RUNNING"],
                TripoConfig.STATUS_CODES["QUEUED"],
            ]:
                raise TripoAPIError(f"Unknown task status: {status}")

            await asyncio.sleep(TripoConfig.POLLING_INTERVAL)

    except Exception as e:
        logging.error(f"Error in receive_one: {str(e)}")
        raise


async def manager_search_task(tid, context):
    try:
        result = await manager_receive_one(tid, context)
        print(result["data"])

        # Extract model URL based on response structure
        glb_model_url = None
        model_type = None
        result_data = result["data"].get("result", {})

        # 按优先级检查三个可能的模型字段
        model_fields = ["pbr_model", "base_model", "model"]

        if result["data"]["input"]["model_version"] in [
            "v2.0-20240919",
            "v2.5-20250123",
        ]:
            # 新版优先检查 pbr_model -> base_model -> model
            for field in model_fields:
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break
        else:
            # 旧版检查顺序 model -> base_model -> pbr_model
            for field in reversed(model_fields):
                if field in result_data:
                    glb_model_url = result_data[field].get("url")
                    model_type = result_data[field].get("type")
                    if glb_model_url:
                        break

        if not glb_model_url:
            raise TripoAPIError(
                "No model URL found in response (checked pbr_model/base_model/model)"
            )

        await manager_gltf_model_download(glb_model_url, context, model_type)

    except Exception as e:
        error_message = f"Error during task search: {str(e)}. Please check the response or contact support."
        show_error_dialog(error_message)


def Update_User_balance(api_key, context):
    headers_tuple = (
        "Content-Type",
        "application/json",
        "Authorization",
        f"Bearer {api_key}",
    )
    response = fetch_data(TripoConfig.get_balance_url(), headers_tuple)
    context.scene.user_balance = str(response["data"]["balance"])


async def gltf_model_download(model_url, context, isTextGenerating, model_type):
    try:
        # 先检查 context.scene.quad  的值
        if model_type == "fbx":  # 如果是 True，使用 FBX 格式
            # 在此设置 FBX 的 URL
            fbx_url = model_url  # 替换为您 FBX 文件的实际 URL
            response = requests.get(fbx_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".fbx", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_fbx_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import FBX model
                        bpy.ops.import_scene.fbx(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # 先设置旋转模式为欧拉XYZ
                            obj.rotation_mode = 'XYZ'
                            # 再旋转到面向+Y方向
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                        # 删除防止重叠的代码
                        # for obj in new_objects:
                        #     obj.location.x += (len(existing_objects) * 0.5)

                    except Exception as e:
                        logging.error(f"Error during FBX import: {str(e)}")
                        raise

                print("Starting FBX Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_fbx_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download FBX model: {response.status_code}")

        else:  # 如果是 False，使用 GLB 格式
            response = requests.get(model_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".glb", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_glb_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import GLB model
                        bpy.ops.import_scene.gltf(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # 先设置旋转模式为欧拉XYZ
                            obj.rotation_mode = 'XYZ'
                            # 再旋转到面向+Y方向
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                        # 删除防止重叠的代码
                        # for obj in new_objects:
                        #     obj.location.x += (len(existing_objects) * 0.5)

                    except Exception as e:
                        logging.error(f"Error during GLB import: {str(e)}")
                        raise

                print("Starting GLB Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_glb_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download GLB model: {response.status_code}")
        if isTextGenerating:
            context.scene.text_is_importing_model = False
        else:
            context.scene.image_is_importing_model = False
    except Exception as e:
        if isTextGenerating:
            context.scene.text_is_importing_model = False
        else:
            context.scene.image_is_importing_model = False
        show_error_dialog(f"Error importing model: {str(e)}")


async def manager_gltf_model_download(model_url, context, model_type):
    try:
        if model_type == "fbx":  # 如果是 True，使用 FBX 格式
            # 在此设置 FBX 的 URL
            fbx_url = model_url  # 替换为您 FBX 文件的实际 URL
            response = requests.get(fbx_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".fbx", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_fbx_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import FBX model
                        bpy.ops.import_scene.fbx(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # 先设置旋转模式为欧拉XYZ
                            obj.rotation_mode = 'XYZ'
                            # 再旋转到面向+Y方向
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                        # 删除防止重叠的代码
                        # for obj in new_objects:
                        #     obj.location.x += (len(existing_objects) * 0.5)

                    except Exception as e:
                        logging.error(f"Error during FBX import: {str(e)}")
                        raise

                print("Starting FBX Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_fbx_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download FBX model: {response.status_code}")

        else:  # 如果是 False，使用 GLB 格式
            response = requests.get(model_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(
                    suffix=".glb", delete=False
                ) as temp_file:
                    temp_file.write(response.content)
                    temp_file_path = temp_file.name

                def import_glb_in_main():
                    try:
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import GLB model
                        bpy.ops.import_scene.gltf(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # 先设置旋转模式为欧拉XYZ
                            obj.rotation_mode = 'XYZ'
                            # 再旋转到面向+Y方向
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                        # 删除防止重叠的代码
                        # for obj in new_objects:
                        #     obj.location.x += (len(existing_objects) * 0.5)

                    except Exception as e:
                        logging.error(f"Error during GLB import: {str(e)}")
                        raise

                print("Starting GLB Import")
                # Execute import in the main thread
                bpy.app.timers.register(import_glb_in_main)

                # Clean up temp file after a delay
                def cleanup():
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logging.error(f"Failed to delete temp file: {str(e)}")

                bpy.app.timers.register(cleanup, first_interval=5.0)

            else:
                raise Exception(f"Failed to download GLB model: {response.status_code}")

    except Exception as e:
        show_error_dialog(f"Error importing model: {str(e)}")


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
        # 绘制表头
        row = box.row()
        row.label(text="TaskID:")
        row.label(text="Status:")
        row.label(text="Options:")

        # 读取存储在场景中的任务状态
        for task in scn.task_status_array:
            row = box.row()
            row.label(text=task.task_id)  # 使用task.task_id
            row.label(text=task.status)  # 使用task.status
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
        """添加新任务到场景"""
        task_status_array = scene.task_status_array

        # 添加新的任务
        new_task = task_status_array.add()
        new_task.task_id = task_id
        new_task.status = status

    def refresh_tasks(self, context):
        """刷新任务状态"""
        scn = context.scene
        task_status_array = scn.task_status_array

        for task in task_status_array:
            task_id = task.task_id
            # 此处应调用真实 API 来获取任务状态
            # status = get_task_status(task_id)
            status = "NEW_STATUS"  # 假设您从 API 获取了新的状态
            # 更新状态
            task.status = status  # 更新状态


class TRIPOD_PT_TripoPluginMainPanel(bpy.types.Panel):
    bl_idname = "TRIPOD_PT_Generate_panel"
    bl_label = "Tripo 3D Generator"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tripo Model Generator"

    def draw(self, context):
        layout = self.layout
        scn = context.scene

        # API KEY 输入部分
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
            row = box.row(align=True)  # 创建一个居中的行布局
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
                row = box.row()
                split = row.split(factor=0.33)
                col = split.column(align=True)
                label_row = col.row()
                label_row.alignment = "CENTER"
                label_row.label(text="FRONT")
                row = col.row()
                row.template_ID_preview(
                    scn, "front_image", open="my_plugin.load_front_image"
                )
                col = split.column(align=True)
                label_row = col.row()
                label_row.alignment = "CENTER"
                label_row.label(text="LEFT")
                row = col.row()
                row.template_ID_preview(
                    scn, "left_image", open="my_plugin.load_left_image"
                )
                col = split.column(align=True)
                label_row = col.row()
                label_row.alignment = "CENTER"
                label_row.label(text="BACK")
                row = col.row()
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
                # 下拉框选择 T-pose 或 A-pose
                row = post_process_box.row()
                row.prop(scn, "pose_type", text="Pose Type")

                # 滑条调整头体高的比率
                row = post_process_box.row()
                row.prop(scn, "head_body_height_ratio", text="Head-Body Height Ratio")
                # 滑条调整头体宽的比率
                row = post_process_box.row()
                row.prop(scn, "head_body_width_ratio", text="Head-Body Width Ratio")
                # 滑条调整腿身高的比率
                row = post_process_box.row()
                row.prop(scn, "legs_body_height_ratio", text="Legs-Body Height Ratio")
                # 滑条调整手臂长度的比率
                row = post_process_box.row()
                row.prop(scn, "arms_body_length_ratio", text="Arms-Body Length Ratio")
                # 滑条调整两个腿之间的距离
                row = post_process_box.row()
                row.prop(scn, "span_of_legs", text="Span of Two Legs")

                # 生成最终的姿势字符串
                pose_string = f", {scn.pose_type}:"
                pose_string += f"{scn.head_body_height_ratio}:"
                pose_string += f"{scn.head_body_width_ratio}:"
                pose_string += f"{scn.legs_body_height_ratio}:"
                pose_string += f"{scn.arms_body_length_ratio}:"
                pose_string += f"{scn.span_of_legs}"
                # row = post_process_box.row()
                # 显示最终的姿势字符串
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


# Operator to start the server
class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Connect to Claude"
    bl_description = "Start the BlenderMCP server to connect with Claude"

    def execute(self, context):
        scene = bpy.context.scene

        # Create a new server instance
        if (
            not hasattr(bpy.types, "blendermcp_server")
            or not bpy.types.blendermcp_server
        ):
            bpy.types.blendermcp_server = BlenderMCPServer(port=scene.blendermcp_port)

        # Start the server
        bpy.types.blendermcp_server.start()
        scene.blendermcp_server_running = True

        return {"FINISHED"}


# Operator to stop the server
class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop the connection to Claude"
    bl_description = "Stop the connection to Claude"

    def execute(self, context):
        scene = bpy.context.scene

        # Stop the server if it exists
        if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
            bpy.types.blendermcp_server.stop()
            del bpy.types.blendermcp_server

        scene.blendermcp_server_running = False

        return {"FINISHED"}


class DownloadTaskOperator(bpy.types.Operator):
    bl_idname = "my_plugin.download_task"
    bl_label = "Download Task"

    task_id: bpy.props.StringProperty()  # 存储任务 ID

    def execute(self, context):
        # 前置检查：task_id 是否为空
        if not self.task_id:
            self.report({"WARNING"}, "Please provide a valid Task ID.")
            return {"CANCELLED"}

        try:
            print("Executing manager_search_task")
            thread = threading.Thread(
                target=lambda: asyncio.run(manager_search_task(self.task_id, context))
            )
            thread.start()
        except Exception as e:
            # 捕获异常并报告错误
            self.report({"ERROR"}, f"An error occurred: {str(e)}")
            return {"CANCELLED"}

        return {"FINISHED"}


class ResetPoseSettings(bpy.types.Operator):
    bl_idname = "pose.reset_pose_settings"
    bl_label = "Reset Pose Settings"
    bl_description = "Reset all pose parameters to default values"

    def execute(self, context):
        # 重置所有参数为默认值
        scene = bpy.context.scene
        scene.pose_type = "T-Pose"
        scene.head_body_height_ratio = 1.0
        scene.head_body_width_ratio = 1.0
        scene.legs_body_height_ratio = 1.0
        scene.arms_body_length_ratio = 1.0
        scene.span_of_legs = 9.0
        return {"FINISHED"}


class MyModelVersionSelector(bpy.types.Operator):
    bl_idname = "object.my_model_version_selector"
    bl_label = "Select Model Version"
    bl_description = "Select a version of the model to load"


class ShowErrorDialog(bpy.types.Operator):
    bl_idname = "error.show_dialog"
    bl_label = "Error"
    bl_options = {"INTERNAL"}

    error_message: bpy.props.StringProperty()

    def execute(self, context):
        # self.report({'ERROR'}, self.error_message)  # 同时记录到 Blender 的报告系统
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(text=self.error_message, icon="ERROR")


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

        # Create headers tuple correctly
        headers_tuple = (
            "Content-Type",
            "application/json",
            "Authorization",
            f"Bearer {scn.api_key}",
        )

        try:
            response = fetch_data(TripoConfig.get_balance_url(), headers_tuple)
            if response["code"] == 0:
                scn.api_key_confirmed = True
                context.scene.user_balance = str(response["data"]["balance"])
                self.save_api_key_to_local(scn.api_key)
                save_handler(None)
                return {"FINISHED"}
            else:
                scn.api_key_confirmed = False
                bpy.ops.error.show_dialog(
                    "INVOKE_DEFAULT", error_message="Invalid API Key!"
                )
                return {"CANCELLED"}
        except requests.RequestException as e:
            scn.api_key_confirmed = False
            bpy.ops.error.show_dialog(
                "INVOKE_DEFAULT", error_message="Network Error: " + str(e)
            )
            return {"CANCELLED"}

    def save_api_key_to_local(self, api_key):
        config_path = os.path.join(os.path.dirname(__file__), "tripo_config.json")
        try:
            with open(config_path, "w") as f:
                json.dump({"api_key": api_key}, f)
        except Exception as e:
            print(f"无法保存API Key到本地: {str(e)}")

        return {"FINISHED"}


class SwitchImageModeOperator(bpy.types.Operator):
    bl_idname = "my_plugin.switch_image_mode"
    bl_label = "Confirm API Key"

    def execute(self, context):
        context.scene.multiview_generate_mode = (
            not context.scene.multiview_generate_mode
        )
        return {"FINISHED"}


class GenerateTextModelOperator(bpy.types.Operator):
    bl_idname = "my_plugin.generate_text_model"
    bl_label = "Generate Text Model"

    def execute(self, context):
        try:
            if context.scene.text_model_generating:
                bpy.ops.error.show_dialog(
                    "INVOKE_DEFAULT",
                    error_message="Generating in progress. Please wait until the current generation is complete before starting a new task.",
                )
                return {"CANCELLED"}

            headers_tuple = (
                "Content-Type",
                "application/json",
                "Authorization",
                f"Bearer {context.scene.api_key}",
            )

            # Create task data using TaskFactory
            data = TaskFactory.create_text_task_data(
                context, context.scene.use_custom_face_limit
            )

            # Send request
            response = fetch_data(
                TripoConfig.get_task_url(), headers_tuple, method="POST", data=data
            )
            task_id = response["data"]["task_id"]

            # Start task monitoring thread
            thread = threading.Thread(
                target=lambda: asyncio.run(search_task(task_id, context, True))
            )
            thread.start()
            context.scene.text_model_generating = True

            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


class LoadImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        scn = context.scene
        image_path = self.filepath

        # 检查路径是否有效
        if not os.path.exists(image_path):
            self.report({"ERROR"}, "Invalid image path")
            return {"CANCELLED"}

        # 加载图像
        try:
            image = bpy.data.images.load(image_path)
            scn.preview_image = image
            scn.image_path = image_path  # 更新路径
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LoadLeftImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_left_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        scn = context.scene
        image_path = self.filepath

        # 检查路径是否有效
        if not os.path.exists(image_path):
            self.report({"ERROR"}, "Invalid image path")
            return {"CANCELLED"}

        # 加载图像
        try:
            image = bpy.data.images.load(image_path)
            scn.left_image = image
            scn.left_image_path = image_path  # 更新路径
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LoadRightImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_right_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        scn = context.scene
        image_path = self.filepath

        # 检查路径是否有效
        if not os.path.exists(image_path):
            self.report({"ERROR"}, "Invalid image path")
            return {"CANCELLED"}

        # 加载图像
        try:
            image = bpy.data.images.load(image_path)
            scn.right_image = image
            scn.right_image_path = image_path  # 更新路径
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LoadFrontImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_front_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        scn = context.scene
        image_path = self.filepath

        # 检查路径是否有效
        if not os.path.exists(image_path):
            self.report({"ERROR"}, "Invalid image path")
            return {"CANCELLED"}

        # 加载图像
        try:
            image = bpy.data.images.load(image_path)
            scn.front_image = image
            scn.front_image_path = image_path  # 更新路径
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LoadBackImageOperator(bpy.types.Operator):
    bl_idname = "my_plugin.load_back_image"
    bl_label = "Load Image from Path"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        scn = context.scene
        image_path = self.filepath

        # 检查路径是否有效
        if not os.path.exists(image_path):
            self.report({"ERROR"}, "Invalid image path")
            return {"CANCELLED"}

        # 加载图像
        try:
            image = bpy.data.images.load(image_path)
            scn.back_image = image
            scn.back_image_path = image_path  # 更新路径
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {str(e)}")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class GenerateImageModelOperator(bpy.types.Operator):
    bl_idname = "my_plugin.generate_image_model"
    bl_label = "Generate Image Model"

    def execute(self, context):
        try:
            if context.scene.image_model_generating:
                bpy.ops.error.show_dialog(
                    "INVOKE_DEFAULT",
                    error_message="Generating in progress. Please wait until the current generation is complete before starting a new task.",
                )
                return {"CANCELLED"}

            if context.scene.multiview_generate_mode:
                # Handle multiview mode
                upload_url = "https://api.tripo3d.ai/v2/openapi/upload"
                headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")

                try:
                    # Upload images and get tokens
                    front_response = upload_file(
                        upload_url, headers_tuple, context.scene.front_image_path
                    )
                    left_response = upload_file(
                        upload_url, headers_tuple, context.scene.left_image_path
                    )
                    back_response = upload_file(
                        upload_url, headers_tuple, context.scene.back_image_path
                    )

                    # Create multiview task data
                    data = {
                        "type": "multiview_to_model",
                        "files": [
                            {
                                "type": "jpg",
                                "file_token": front_response["data"]["image_token"],
                            },
                            {
                                "type": "jpg",
                                "file_token": left_response["data"]["image_token"],
                            },
                            {
                                "type": "jpg",
                                "file_token": back_response["data"]["image_token"],
                            },
                            {},  # This empty bracket is required according to the original script
                        ],
                        "model_version": context.scene.model_version,
                        "mode": "LEFT",
                    }

                    # Add v2.0 specific parameters if needed
                    if (
                        context.scene.model_version == "v2.0-20240919"
                        or context.scene.model_version == "v2.5-20250123"
                    ):
                        data.update(
                            {
                                "quad": context.scene.quad,
                                "texture": context.scene.texture,
                                "pbr": context.scene.pbr,
                                "texture_seed": int(context.scene.texture_seed),
                                "texture_alignment": context.scene.texture_alignment,
                                "texture_quality": context.scene.texture_quality,
                                "auto_size": context.scene.auto_size,
                                "orientation": context.scene.orientation,
                            }
                        )
                        if context.scene.use_custom_face_limit:
                            data["face_limit"] = int(context.scene.face_limit)

                    # Log the request data for debugging
                    logging.info(
                        f"Multiview request data: {json.dumps(data, indent=2)}"
                    )

                except Exception as e:
                    logging.error(f"Error during multiview upload: {str(e)}")
                    show_error_dialog(f"Error uploading images: {str(e)}")
                    return {"CANCELLED"}

            else:
                # Handle single image mode
                upload_url = "https://api.tripo3d.ai/v2/openapi/upload"
                headers_tuple = ("Authorization", f"Bearer {context.scene.api_key}")

                # 检查是来自文件还是来自Blender内部
                if context.scene.image_path != "----":
                    # 从文件加载的图片
                    is_valid, error_message = validate_image_file(context.scene.image_path)
                    if not is_valid:
                        show_error_dialog(error_message)
                        return {"CANCELLED"}
                    image_path = context.scene.image_path
                elif context.scene.preview_image:
                    # 从Blender内部使用的图片
                    # 需要先保存到临时文件
                    image = context.scene.preview_image
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                    temp_path = temp_file.name
                    temp_file.close()
                    
                    # 保存图片到临时文件
                    image.save_render(temp_path)
                    image_path = temp_path
                else:
                    show_error_dialog("No image selected")
                    return {"CANCELLED"}

                response = upload_file(upload_url, headers_tuple, image_path)
                file_token = response["data"]["image_token"]
                
                # 如果是临时文件，使用完后删除
                if context.scene.image_path == "----" and context.scene.preview_image:
                    try:
                        os.unlink(image_path)
                    except:
                        pass

                # Create task data
                data = TaskFactory.create_image_task_data(
                    context, file_token, context.scene.use_custom_face_limit
                )

            # Send request
            headers_tuple = (
                "Content-Type",
                "application/json",
                "Authorization",
                f"Bearer {context.scene.api_key}",
            )
            response = fetch_data(
                TripoConfig.get_task_url(), headers_tuple, method="POST", data=data
            )
            task_id = response["data"]["task_id"]

            # Start task monitoring thread
            thread = threading.Thread(
                target=lambda: asyncio.run(search_task(task_id, context, False))
            )
            thread.start()
            context.scene.image_model_generating = True

            return {"FINISHED"}

        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}


def calculate_text_to_model_price(scene):
    price = 0

    # 获取模型版本
    model_version = scene.model_version
    texture_option = scene.texture
    texture_quality = scene.texture_quality
    quad_option = scene.quad
    style_option = scene.style

    # 确定基础价格
    if model_version in ["v2.5-20250123", "v2.0-20240919"]:
        # 无纹理
        if not texture_option:
            price = 10  # 无纹理文生模型
        elif texture_quality == "standard":
            price = 20  # 标准纹理文生模型
        elif texture_quality == "detailed":
            price = 30  # 高清纹理文生模型

        # 额外费用
        if quad_option:
            price += 5  # Quad 附加费用
        if style_option != "original":
            price += 5  # 其他样式附加费用

    elif model_version in ["v1.4-20240625", "v1.3-20240522"]:
        # 仅适用于模型版本 2 和 3
        price = 20  # 文生模型

    return price


def calculate_image_to_model_price(scene):
    price = 0

    # 获取模型版本
    model_version = scene.model_version
    texture_option = scene.texture
    texture_quality = scene.texture_quality
    quad_option = scene.quad
    style_option = scene.style

    # 确定基础价格
    if model_version in ["v2.5-20250123", "v2.0-20240919"]:
        # 无纹理
        if not texture_option:
            price = 20  # 无纹理图生模型
        elif texture_quality == "standard":
            price = 30  # 标准纹理图生模型
        elif texture_quality == "detailed":
            price = 40  # 高清纹理图生模型

        # 额外费用
        if quad_option:
            price += 5  # Quad 附加费用
        if style_option != "original":
            price += 5  # 其他样式附加费用

    elif model_version in ["v1.4-20240625", "v1.3-20240522"]:
        # 仅适用于模型版本 2 和 3
        price = 30  # 图生模型

    return price


def update_preview_image(self, context):
    """当预览图片被更改时调用"""
    if self.ma_preview_image is None:
        self.show_preview = False
        self.image_path = ""
        self.image_token = ""


class ImagePreviewProps(bpy.types.PropertyGroup):
    image_path: bpy.props.StringProperty(
        name="图片路径", description="选择的图片路径", subtype="FILE_PATH", default=""
    )

    show_preview: bpy.props.BoolProperty(
        name="显示预览", description="切换图片预览显示", default=False
    )

    ma_preview_image: bpy.props.PointerProperty(
        type=bpy.types.Image, name="预览图片", update=update_preview_image
    )

    image_token: bpy.props.StringProperty(
        name="Image Token",
        description="The token of the image",
        default="",
    )


def register_custom_properties():
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
            ("v1.3-20240522", "Version 1.3", "2024-05-22 version of the model"),
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
        name="user_balance", default="----"
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

    bpy.types.Scene.info_text = bpy.props.StringProperty(
        default="The multi-view generation feature in versions 1.3 and 1.4 will soon be discontinued to make way for version 2.5. Please look forward to the amazing performance of version 2.5!"
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
            ("original", "Original style", "Keep the original style and appearance"),
            (
                "person:person2cartoon",
                "Cartoon",
                "Transforms the model into a cartoon-style version of the input character.",
            ),
            ("object:clay", "Clay", "Applies a clay-like appearance to the object."),
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
            ("object:barbie", "Barbie", "Applies a barbie style to the object."),
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

    # 文件过滤器（仅在文件选择对话框中显示这些类型的文件）
    bpy.types.Scene.image_path = bpy.props.StringProperty(
        name="image_path", default="----"
    )
    bpy.types.Scene.front_image_path = bpy.props.StringProperty(
        name="front_image_path", default="----"
    )
    bpy.types.Scene.left_image_path = bpy.props.StringProperty(
        name="left_image_path", default="----"
    )
    bpy.types.Scene.back_image_path = bpy.props.StringProperty(
        name="back_image_path", default="----"
    )
    bpy.types.Scene.right_image_path = bpy.props.StringProperty(
        name="right_image_path", default="----"
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


# 注册和注销函数
def register():
    if bpy.app.version < bl_info["blender"]:
        msg = (
            f"Addon requires Blender {'.'.join(map(str, bl_info['blender']))} or newer"
        )
        raise Exception(msg)

    bpy.types.Scene.blendermcp_port = IntProperty(
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

    bpy.utils.register_class(BLENDERMCP_OT_StartServer)
    bpy.utils.register_class(BLENDERMCP_OT_StopServer)
    bpy.utils.register_class(MyModelVersionSelector)
    bpy.utils.register_class(SwitchImageModeOperator)

    bpy.utils.register_class(TRIPOD_PT_TripoPluginMainPanel)
    bpy.utils.register_class(ConfirmApiKeyOperator)
    bpy.utils.register_class(GenerateTextModelOperator)
    bpy.utils.register_class(ShowErrorDialog)

    bpy.utils.register_class(GenerateImageModelOperator)
    bpy.utils.register_class(ImagePreviewProps)
    bpy.utils.register_class(LoadLeftImageOperator)
    bpy.utils.register_class(LoadRightImageOperator)
    bpy.utils.register_class(LoadFrontImageOperator)
    bpy.utils.register_class(LoadBackImageOperator)
    bpy.utils.register_class(LoadImageOperator)
    bpy.utils.register_class(TripoSettings)
    bpy.utils.register_class(ResetPoseSettings)
    bpy.utils.register_class(TaskStatus)
    bpy.utils.register_class(TRIPOD_PT_TripoPluginManagerPanel)
    bpy.utils.register_class(DownloadTaskOperator)
    bpy.types.Scene.tripo_settings = bpy.props.PointerProperty(type=TripoSettings)
    register_custom_properties()
    register_error_handlers()
    bpy.types.Scene.last_import_time = bpy.props.FloatProperty(default=0.0)
    bpy.app.handlers.load_post.append(load_api_key_from_local)


def unregister():
    if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
        bpy.types.blendermcp_server.stop()
        del bpy.types.blendermcp_server

    bpy.utils.unregister_class(BLENDERMCP_OT_StartServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_StopServer)

    del bpy.types.Scene.blendermcp_port
    del bpy.types.Scene.blendermcp_server_running
    del bpy.types.Scene.blendermcp_use_polyhaven
    bpy.utils.unregister_class(MyModelVersionSelector)
    bpy.utils.unregister_class(SwitchImageModeOperator)

    bpy.utils.unregister_class(TRIPOD_PT_TripoPluginMainPanel)
    bpy.utils.unregister_class(ConfirmApiKeyOperator)
    bpy.utils.unregister_class(GenerateTextModelOperator)
    bpy.utils.unregister_class(ShowErrorDialog)

    bpy.utils.unregister_class(GenerateImageModelOperator)
    bpy.utils.unregister_class(ImagePreviewProps)
    bpy.utils.unregister_class(LoadLeftImageOperator)
    bpy.utils.unregister_class(LoadRightImageOperator)
    bpy.utils.unregister_class(LoadFrontImageOperator)
    bpy.utils.unregister_class(LoadBackImageOperator)
    bpy.utils.unregister_class(LoadImageOperator)
    bpy.utils.unregister_class(TripoSettings)
    bpy.utils.unregister_class(ResetPoseSettings)
    bpy.utils.unregister_class(TaskStatus)
    bpy.utils.unregister_class(TRIPOD_PT_TripoPluginManagerPanel)
    bpy.utils.unregister_class(DownloadTaskOperator)
    del bpy.types.Scene.tripo_settings

    if hasattr(bpy.types.Scene, "last_ui_update"):
        del bpy.types.Scene.last_ui_update

    # Clear the API key from the property group
    if hasattr(bpy.context.scene, "tripo_settings"):
        bpy.context.scene.tripo_settings.api_key = ""

    # Unregister other properties
    del bpy.types.Scene.api_key_confirmed
    del bpy.types.Scene.text_prompts
    del bpy.types.Scene.image_path
    del bpy.types.Scene.text_model_generating
    del bpy.types.Scene.text_generating_percentage
    del bpy.types.Scene.image_model_generating
    del bpy.types.Scene.image_generating_percentage
    del bpy.types.Scene.user_balance
    del bpy.types.Scene.face_limit
    del bpy.types.Scene.texture
    del bpy.types.Scene.pbr
    del bpy.types.Scene.texture_seed
    del bpy.types.Scene.texture_alignment
    del bpy.types.Scene.texture_quality
    del bpy.types.Scene.auto_size
    del bpy.types.Scene.style
    del bpy.types.Scene.orientation
    del bpy.types.Scene.preview_image
    del bpy.types.Scene.task_status_array

    # Add these to the existing cleanup
    if hasattr(bpy.types.Scene, "generation_elapsed_time"):
        del bpy.types.Scene.generation_elapsed_time
    if hasattr(bpy.types.Scene, "generation_status"):
        del bpy.types.Scene.generation_status

    unregister_error_handlers()


def _label_multiline(context, text, parent):
    chars = int(context.region.width / 11)  # 7 pix on 1 character
    wrapper = textwrap.TextWrapper(width=chars)
    text_lines = wrapper.wrap(text=text)
    for text_line in text_lines:
        parent.label(text=text_line)


# 保存场景时自动保存属性
def save_handler(dummy):
    # 这里可以添加代码来处理保存前的逻辑
    # 获取当前场景
    scene = bpy.context.scene
    # 添加逻辑来处理保存前的逻辑
    # 例如，可以打印当前的 API Key 和确认状态
    print("Saving Scene...")
    print("API Key:", scene.api_key)
    print("API Key Confirmed:", scene.api_key_confirmed)


# 加载场景时自动加载属性
def load_handler(dummy):
    # 这里可以添加代码来处理加载后的逻辑
    scene = bpy.context.scene
    # 添加逻辑来处理加载后的逻辑
    # 例如，可以打印加载后的 API Key 和确认状态
    print("Loading Scene...")
    print("API Key:", scene.api_key)
    print("API Key Confirmed:", scene.api_key_confirmed)
    Update_User_balance(scene.api_key, bpy.context)


class TaskStatus(bpy.types.PropertyGroup):
    task_id: bpy.props.StringProperty(name="Task ID", default="")
    status: bpy.props.StringProperty(name="Status", default="")


class TripoError(Exception):
    """Base exception class for Tripo addon errors"""

    pass


class TripoAPIError(TripoError):
    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response

        # Updated error codes from API documentation
        self.ERROR_CODES = {
            2000: "You have exceeded the limit of generation",
            2002: "The task type is unsupported.",
            2006: "The type of the input original task is invalid.",
            2007: "The status of the original task is not success.",
            2010: "You need more credits to start a new task.",
            1000: "Unknown error. Please contact the support team with the trace id.",
            1001: "Fatal error.	Please contact the support team with the trace id.",
            1002: "Unauthorized	Please ensure that the API key is still valid and that it has been entered in the correct format.",
            1003: "The request is malformed. Please check if the request body is json and matches the requirements of the endpoint.",
            1004: "Bad parameter(s). Please check if the request body matches the requirements of the endpoint.",
            1005: "Forbidden. Your request is rejected. Please ensure you have the authority to access the endpoint.",
        }

    @classmethod
    def from_response(cls, response):
        """Create error from API response"""
        try:
            data = response.json()
            message = data.get("message", "Unknown error")
            code = data.get("code", response.status_code)
            return cls(
                message=f"{cls.ERROR_CODES.get(code, 'Unknown error')}: {message}",
                status_code=response.status_code,
                response=response,
            )
        except ValueError:
            return cls(f"HTTP {response.status_code}", status_code=response.status_code)


@bpy.app.handlers.persistent
def load_api_key_from_local(dummy):
    config_path = os.path.join(os.path.dirname(__file__), "tripo_config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
                bpy.context.scene.api_key = config.get("api_key", "")
                bpy.context.scene.api_key_confirmed = True
    except Exception as e:
        print(f"无法从本地加载API Key: {str(e)}")


def handle_api_error(error):
    if isinstance(error, requests.exceptions.ConnectionError):
        return "Network connection error. Please check your internet connection."
    elif isinstance(error, requests.exceptions.Timeout):
        return "Request timed out. Please try again."
    elif isinstance(error, TripoAPIError):
        return f"API Error ({error.status_code}): {str(error)}"
    else:
        return f"Unexpected error: {str(error)}"


class TripoNetworkError(TripoError):
    """Raised when network operations fail"""

    pass


class TripoValidationError(TripoError):
    """Raised when input validation fails"""

    pass


def show_error_message(self, context, message):
    def draw(self, context):
        self.layout.label(text=message)

    bpy.context.window_manager.popup_menu(draw, title="Error", icon="ERROR")

    # Usage in error handling:
    try:
        # API call or other operation
        pass
    except TripoAPIError as e:
        show_error_message(self, context, str(e))


class ResourceManager:
    def __init__(self):
        self.temp_files = []

    def create_temp_file(self, suffix=None):
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        self.temp_files.append(temp.name)
        return temp.name

    def cleanup(self):
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                logger.error(f"Failed to delete temporary file {temp_file}: {str(e)}")
        self.temp_files.clear()


# Usage:
resource_manager = ResourceManager()
try:
    temp_file = resource_manager.create_temp_file(suffix=".glb")
    # Use temp_file
finally:
    resource_manager.cleanup()

if __name__ == "__main__":
    # 注册保存和加载处理器
    bpy.app.handlers.save_post.append(save_handler)
    bpy.app.handlers.load_post.append(load_handler)
    register()


class TripoAPIClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers_tuple = (
            "Content-Type",
            "application/json",
            "Authorization",
            f"Bearer {self.api_key}",
        )

    def get_balance(self):
        return fetch_data(TripoConfig.get_balance_url(), self.headers_tuple)

    def create_task(self, data):
        return fetch_data(
            TripoConfig.get_task_url(), self.headers_tuple, method="POST", data=data
        )

    def get_task_status(self, task_id):
        return fetch_data(TripoConfig.get_task_url(task_id), self.headers_tuple)

    def upload_file(self, file_path):
        headers_tuple = ("Authorization", f"Bearer {self.api_key}")
        with open(file_path, "rb") as f:
            files = {"file": (file_path, f, "image/jpeg")}
            response = fetch_data(
                TripoConfig.UPLOAD_ENDPOINT, headers_tuple, files=files
            )
        return response["data"]["image_token"]


class TaskManager:
    def __init__(self, context, api_client):
        self.context = context
        self.api_client = api_client
        self.resource_manager = ResourceManager()

    def create_text_task(self, prompt, options=None):
        data = {
            "type": "text_to_model",
            "model_version": self.context.scene.model_version,
            "prompt": prompt,
        }
        if options:
            data.update(options)

        response = self.api_client.create_task(data)
        return response["data"]["task_id"]

    def create_image_task(self, image_path, options=None):
        file_token = self.api_client.upload_file(image_path)
        data = {
            "type": "image_to_model",
            "model_version": self.context.scene.model_version,
            "file": {"type": "jpg", "file_token": file_token},
        }
        if options:
            data.update(options)

        response = self.api_client.create_task(data)
        return response["data"]["task_id"]


class ModelImporter:
    _import_lock = threading.Lock()

    @classmethod
    async def import_model(cls, model_url, api_key, context):
        with cls._import_lock:
            try:
                response = requests.get(model_url)
                if response.status_code == 200:
                    with tempfile.NamedTemporaryFile(
                        suffix=".glb", delete=False
                    ) as temp_file:
                        temp_file.write(response.content)
                        temp_file_path = temp_file.name

                    # Import in the main thread
                    def import_in_main():
                        # Ensure we're in object mode before import
                        if bpy.context.mode != 'OBJECT':
                            bpy.ops.object.mode_set(mode='OBJECT')
                            
                        # Deselect all objects first
                        bpy.ops.object.select_all(action="DESELECT")

                        # Store current objects
                        existing_objects = set(bpy.data.objects[:])

                        # Import new model
                        bpy.ops.import_scene.gltf(filepath=temp_file_path)

                        # Select only newly added objects
                        new_objects = set(bpy.data.objects[:]) - existing_objects
                        for obj in new_objects:
                            obj.select_set(True)
                            # 先设置旋转模式为欧拉XYZ
                            obj.rotation_mode = 'XYZ'
                            # 再旋转到面向+Y方向
                            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

                        # Set active object to one of the new objects if any were added
                        if new_objects:
                            bpy.context.view_layer.objects.active = list(new_objects)[0]

                    bpy.app.timers.register(import_in_main)

                    # Clean up temp file after a delay
                    def cleanup():
                        try:
                            os.unlink(temp_file_path)
                        except Exception as e:
                            logging.error(f"Failed to delete temp file: {str(e)}")

                    bpy.app.timers.register(cleanup, first_interval=5.0)

                else:
                    raise TripoAPIError(
                        f"Failed to download model: {response.status_code}"
                    )

            except Exception as e:
                logging.error(f"Error importing model: {str(e)}")
                raise


class TaskFactory:
    @staticmethod
    def create_text_task_data(context, use_custom_face_limit=False):
        data = {"type": "text_to_model", "model_version": context.scene.model_version}
        if context.scene.use_pose_control:
            pose_string = f", {context.scene.pose_type}:"
            pose_string += f"{context.scene.head_body_height_ratio}:"
            pose_string += f"{context.scene.head_body_width_ratio}:"
            pose_string += f"{context.scene.legs_body_height_ratio}:"
            pose_string += f"{context.scene.arms_body_length_ratio}:"
            pose_string += f"{context.scene.span_of_legs}"
            context.scene.text_prompts_with_pose = (
                context.scene.text_prompts + pose_string
            )
            data["prompt"] = context.scene.text_prompts_with_pose
        else:
            data["prompt"] = context.scene.text_prompts
        if context.scene.enable_negative_prompts:
            data["negative_prompt"] = context.scene.negative_prompts
        if (
            context.scene.model_version == "v2.0-20240919"
            or context.scene.model_version == "v2.5-20250123"
        ):
            data.update(
                {
                    "quad": context.scene.quad,
                    "texture": context.scene.texture,
                    "pbr": context.scene.pbr,
                    "texture_seed": int(context.scene.texture_seed),
                    "texture_quality": context.scene.texture_quality,
                    "auto_size": context.scene.auto_size,
                }
            )

            if context.scene.style != "original":
                data["style"] = context.scene.style

            if use_custom_face_limit:
                data["face_limit"] = int(context.scene.face_limit)

        return data

    @staticmethod
    def create_image_task_data(context, file_token, use_custom_face_limit=False):
        data = {
            "type": "image_to_model",
            "model_version": context.scene.model_version,
            "file": {"type": "jpg", "file_token": file_token},
        }

        if (
            context.scene.model_version == "v2.0-20240919"
            or context.scene.model_version == "v2.5-20250123"
        ):
            # Add v2.0 specific parameters
            data.update(
                {
                    "quad": context.scene.quad,
                    "texture": context.scene.texture,
                    "pbr": context.scene.pbr,
                    "texture_seed": int(context.scene.texture_seed),
                    "texture_alignment": context.scene.texture_alignment,
                    "texture_quality": context.scene.texture_quality,
                    "auto_size": context.scene.auto_size,
                    "orientation": context.scene.orientation,
                }
            )

            if use_custom_face_limit:
                data["face_limit"] = int(context.scene.face_limit)

        return data

    @staticmethod
    def create_animation_task_data(context, model_url, animation_type):
        """Create data for animation tasks"""
        data = {
            "type": TripoConfig.TASK_TYPES["ANIMATION"],
            "model_url": model_url,
            "animation_type": animation_type,
        }
        return data

    @staticmethod
    def create_post_process_task_data(context, model_url, options):
        """Create data for post-processing tasks"""
        data = {"type": TripoConfig.TASK_TYPES["POST_PROCESS"], "model_url": model_url}
        if options:
            data.update(options)
        return data


def validate_config(context):
    """Validate configuration before starting a task"""
    errors = []

    if not context.scene.api_key:
        errors.append("API key is required")

    if context.scene.use_custom_face_limit and context.scene.face_limit < 100:
        errors.append("Face limit must be at least 100")

    if (
        context.scene.model_version == "v2.0-20240919"
        or context.scene.model_version == "v2.5-20250123"
    ):
        if context.scene.texture_seed < 0:
            errors.append("Texture seed must be non-negative")

    return errors


def validate_image_file(file_path):
    """
    Validate an image file before upload

    Args:
        file_path: Path to the image file

    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return False, "File does not exist"

        # Check file size
        if os.path.getsize(file_path) > TripoConfig.MAX_FILE_SIZE:
            return (
                False,
                f"File size exceeds {TripoConfig.MAX_FILE_SIZE / 1024 / 1024}MB limit",
            )

        # Check file type
        ext = os.path.splitext(file_path)[1][1:].lower()
        if ext not in TripoConfig.SUPPORTED_FILE_TYPES:
            return (
                False,
                f"Unsupported file type. Supported: {', '.join(TripoConfig.SUPPORTED_FILE_TYPES.keys())}",
            )

        return True, ""

    except Exception as e:
        return False, f"Error validating file: {str(e)}"


def register_error_handlers():
    """Register error handlers for crash recovery and cleanup"""

    def handle_blender_crash(*args):
        logging.error("Blender crash detected")
        # Clean up temporary files
        temp_dir = tempfile.gettempdir()
        for file in os.listdir(temp_dir):
            if file.startswith("tripo_") and file.endswith(".glb"):
                try:
                    os.unlink(os.path.join(temp_dir, file))
                except Exception as e:
                    logging.error(f"Failed to delete temporary file {file}: {str(e)}")

    # Register the handler for load_post event
    if handle_blender_crash not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(handle_blender_crash)


def unregister_error_handlers():
    """Unregister error handlers"""
    # Remove all handlers we added
    for handler in bpy.app.handlers.load_post:
        if handler.__name__ == "handle_blender_crash":
            bpy.app.handlers.load_post.remove(handler)

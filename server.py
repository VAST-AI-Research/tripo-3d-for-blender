import bpy
import socket
import json
import traceback
import requests
import tempfile
import os
from .config import get_logger

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
            get_logger().info(f"BlenderMCP server started on {self.host}:{self.port}")
        except Exception as e:
            get_logger().exception(f"Failed to start server: {str(e)}")
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
        get_logger().info("BlenderMCP server stopped")

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
                    get_logger().info(f"Connected to client: {address}")
                except BlockingIOError:
                    pass  # No connection waiting
                except Exception as e:
                    get_logger().exception(f"Error accepting connection: {str(e)}")

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
                            get_logger().warn("Client disconnected")
                            self.client.close()
                            self.client = None
                            self.buffer = b""
                    except BlockingIOError:
                        pass  # No data available
                    except Exception as e:
                        get_logger().exeption(f"Error receiving data: {str(e)}")
                        self.client.close()
                        self.client = None
                        self.buffer = b""

                except Exception as e:
                    get_logger().exeption(f"Error with client: {str(e)}")
                    if self.client:
                        self.client.close()
                        self.client = None
                    self.buffer = b""

        except Exception as e:
            get_logger().exeption(f"Server error: {str(e)}")

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
            get_logger().exception(f"Error executing command: {str(e)}")

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
                get_logger().info(f"Executing handler for {cmd_type}")
                result = handler(**params)
                get_logger().info(f"Handler execution complete")
                return {"status": "success", "result": result}
            except Exception as e:
                get_logger().exception(f"Error in handler: {str(e)}")
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
            # First set rotation mode to Euler XYZ
            obj.rotation_mode = 'XYZ'
            # Then rotate to face +Y direction
            obj.rotation_euler[2] = obj.rotation_euler[2] + 1.5708  # 90 degrees in radians

            # Calculate bounding box dimensions
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
            get_logger().info("Getting scene info...")
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

            get_logger().info(f"Scene info collected: {len(scene_info['objects'])} objects")
            return scene_info
        except Exception as e:
            get_logger().exception(f"Error in get_scene_info: {str(e)}")
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
                    get_logger().info(f"Created new material: {material_name}")
            else:
                # Generate unique material name if none provided
                mat_name = f"{object_name}_material"
                mat = bpy.data.materials.get(mat_name)
                if not mat:
                    mat = bpy.data.materials.new(name=mat_name)
                material_name = mat_name
                get_logger().info(f"Using material: {mat_name}")

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
                    get_logger().info(f"Set material color to {color}")

            # Assign material to object if not already assigned
            if mat:
                if not obj.data.materials:
                    obj.data.materials.append(mat)
                else:
                    # Only modify first material slot
                    obj.data.materials[0] = mat

                get_logger().info(f"Assigned material {mat.name} to object {object_name}")

                return {
                    "status": "success",
                    "object": object_name,
                    "material": mat.name,
                    "color": color if color else None,
                }
            else:
                raise ValueError(f"Failed to create or find material: {material_name}")

        except Exception as e:
            get_logger().exception(f"Error in set_material: {str(e)}")
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

    # PolyHaven相关功能被精简掉

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
        """Get current Tripo API key status"""
        api_key = bpy.context.scene.api_key
        if api_key:
            if api_key.startswith('tsk_'):
                get_logger().info("API key is configured")
            else:
                get_logger().error("Invalid API key, it should start with tsk_")
        else:
            get_logger().error("API key not found, please configure in the plugin panel")
        return {
            "configured": bool(api_key),
            "api_key": api_key,
            "message": "API key is configured"
            if api_key
            else "API key not found, please configure in the plugin panel",
        } 
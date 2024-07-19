import bpy
import bmesh
import math

def snap_uvs_to_nearest_pixel(image, uv_layer, bm):
    width, height = image.size
    
    for face in bm.faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            uv[0] = round(uv[0] * width) / width
            uv[1] = round(uv[1] * height) / height

def fix_zero_dimensional_edges(image, uv_layer, bm):
    width, height = image.size
    pixel_width = 1.0 / width
    pixel_height = 1.0 / height
    
    for face in bm.faces:
        uvs = [loop[uv_layer].uv for loop in face.loops]
        unique_uvs = {tuple(uv) for uv in uvs}
        if len(unique_uvs) == 1:
            base_uv = uvs[0]
            uvs[1][0] = base_uv[0] + pixel_width / 3
            uvs[1][1] = base_uv[1]
            uvs[2][0] = base_uv[0]
            uvs[2][1] = base_uv[1] + pixel_height / 3

def main():
    selected_objects = bpy.context.selected_objects
    
    if not selected_objects:
        print("No objects selected.")
        return
    
    image = None
    for obj in selected_objects:
        if obj.type != 'MESH':
            continue
        
        for mat_slot in obj.material_slots:
            if mat_slot.material and mat_slot.material.use_nodes:
                for node in mat_slot.material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        image = node.image
                        break
                if image:
                    break
        if image:
            break
    
    if not image:
        print("No common image found for UV maps.")
        return
    
    for obj in selected_objects:
        if obj.type != 'MESH':
            continue
        
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)
        
        uv_layer = bm.loops.layers.uv.verify()
        
        uv_loop_layer = bm.loops.layers.uv.active
        
        if uv_loop_layer is None:
            print(f"No UV map found for object {obj.name}.")
            bpy.ops.object.mode_set(mode='OBJECT')
            continue
        
        snap_uvs_to_nearest_pixel(image, uv_layer, bm)
        fix_zero_dimensional_edges(image, uv_layer, bm)
        
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')
    
    print("UV snapping completed for all selected objects.")

if __name__ == "__main__":
    main()

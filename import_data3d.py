import os
import sys
import mathutils
import logging
import array
import time

import bpy
from bpy_extras.io_utils import unpack_list
import bmesh

from . import material_utils
from io_scene_data3d.data3d_utils import D3D, deserialize_data3d
from io_scene_data3d.material_utils import Material


# Global Variables
C = bpy.context
D = bpy.data
O = bpy.ops

log = logging.getLogger('archilogic')


def import_data3d_materials(data3d_objects, filepath, import_metadata):
    """ Import the material references and create blender and cycles materials and add the hashed keys
        and add a material-hash-map to the data3d_objects dictionary.
        Args:
            data3d_objects ('dict') - The data3d_objects and materials to import.
            filepath ('str') - The file path to the source file.
            import_metadata ('bool') - Import Archilogic json-material as blender-material metadata.
        Returns:
            bl_materials ('dict') - Dictionary of hashed material keys and corresponding blender-material references.
    """

    def get_al_material_hash(al_material):
        """ Hash the relevant json material data and return a reduced al_material.
            Args:
                al_material ('dict') - The source al_material dict.
            Returns:
                al_mat_hash ('int') - The hashed dictionary.
                hash_nodes ('dict') - The al_material dictionary reduced to the relevant keys.
        """
        # FIXME solution for Baking related material info (we only need this for internal purposes
        compare_keys = [D3D.col_diff,
                        D3D.col_spec,
                        D3D.coef_spec,
                        D3D.coef_emit,
                        D3D.opacity,
                        D3D.uv_scale,
                        D3D.map_diff, D3D.map_diff + D3D.map_suffix_source, D3D.map_diff + D3D.map_suffix_preview,
                        D3D.map_spec, D3D.map_spec + D3D.map_suffix_source, D3D.map_spec + D3D.map_suffix_preview,
                        D3D.map_norm, D3D.map_norm + D3D.map_suffix_source, D3D.map_norm + D3D.map_suffix_preview,
                        D3D.map_alpha, D3D.map_alpha + D3D.map_suffix_source, D3D.map_alpha + D3D.map_suffix_preview,
                        D3D.map_light, D3D.map_light + D3D.map_suffix_source, D3D.map_light + D3D.map_suffix_preview,
                        D3D.cast_shadows,
                        D3D.receive_shadows]
        # Import material info for internal purposes.
        if import_metadata:
            compare_keys.extend([D3D.add_lightmap, D3D.use_in_calc, D3D.hide_after_calc])
        hash_nodes = {}
        for key in compare_keys:
            if key in al_material:
                value = al_material[key]
                hash_nodes[key] = tuple(value) if isinstance(value, list) else value
        al_mat_hash = hash(frozenset(hash_nodes.items()))
        return al_mat_hash, hash_nodes

    material_utils.setup()
    al_hashed_materials = {}

    for data3d_object in data3d_objects:
        al_raw_materials = data3d_object.materials
        material_hash_map = {}
        for key in al_raw_materials:
            al_mat_hash, al_mat = get_al_material_hash(al_raw_materials[key])
            # Add hash to the data3d_object json
            material_hash_map[key] = str(al_mat_hash)
            # Check if the material already exists
            if al_mat_hash not in al_hashed_materials:
                al_hashed_materials[al_mat_hash] = al_mat

        data3d_object.mat_hash_map = material_hash_map

    # Create the Blender Materials
    bl_materials = {}
    working_dir = os.path.dirname(filepath)
    for key in al_hashed_materials:
        mat = Material(str(key), al_hashed_materials[key], import_metadata, working_dir)
        bl_materials[str(key)] = mat
    return bl_materials


def import_scene(data3d_objects, **kwargs):
    """ Import the data3d file as a blender scene
        Args:
            data3d_objects ('Data3dObject') - The deserialized data3d objects.
        Kwargs:
            filepath ('str') - The file path to the data3d source file.
            import_materials ('bool') - Import materials.
            import_materials ('bool') - Import and apply materials.
            import_hierarchy ('bool') - Import and keep the parent-child hierarchy.
            import_al_metadata ('bool') - Import the Archilogic data as metadata.
            global_matrix ('Matrix') - The global orientation matrix to apply.
    """

    filepath = kwargs['filepath']
    import_materials = kwargs['import_materials']
    import_hierarchy = kwargs['import_hierarchy']
    global_matrix = kwargs['global_matrix']

    perf_times = {}

    def optimize_mesh(obj, remove_isolated=True, check_triangles=True):
        """ Remove isolated edges, vertices, faces that do not span a triangle. Convert triangles to quads.
            Args:
                obj ('bpy_types.Object') - Object (Mesh) to be cleaned.
            Kwargs:
                remove_isolated ('bool') - Remove isolated edges and vertices (Default=True)
                check_triangles ('bool') - Remove polygons that don't span a triangle (Default=True)
        """
        if obj is None:
            return
        if obj.type != 'MESH':
            return
        select(obj, discard_selection=True)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        update_mesh = False

        info = []

        def face_spans_triangle(f):
            threshold = 0.00000001  # SMALL_NUM / Blender limitation
            if f.calc_area() <= threshold:
                return False
            return True

        def edge_is_isolated(e):
            return e.is_wire

        def vertex_is_isolated(v):
            return not bool(v.link_edges)

        if check_triangles:
            # Remove Faces that don't span a triangle
            remove_elements = [face for face in bm.faces if not face_spans_triangle(face)]
            for face in remove_elements:
                bm.faces.remove(face)
            update_mesh |= bool(remove_elements)
            info.append('faces removed: %d' % len(remove_elements))
            del remove_elements

        if remove_isolated:
            # Remove isolated edges and vertices
            remove_elements = [edge for edge in bm.edges if edge_is_isolated(edge)]
            for edge in remove_elements:
                bm.edges.remove(edge)
            update_mesh |= bool(remove_elements)
            info.append('edges removed: %d' % len(remove_elements))
            del remove_elements

            remove_elements = [vertex for vertex in bm.verts if vertex_is_isolated(vertex)]
            for vertex in remove_elements:
                bm.verts.remove(vertex)
            update_mesh |= bool(remove_elements)
            info.append('vertices removed: %d' % len(remove_elements))
            del remove_elements

        # # Remove empty meshes
        # if len(bm.faces) <= 0:
        #     # Mesh does not have to be updated, since the object will be deleted entirely
        #     update_mesh = False
        #     bpy.ops.object.delete(use_global=True)
        #     info.append('Deleted object because it contains no relevant geometry')

        #if info:
        #    log.debug('Clean mesh info: %s' % info)
        if update_mesh:
            bm.to_mesh(obj.data)
        bm.free()

        # TODO Make tris to quads hidden option for operator (internal use)
        # Fixme: Performance of ops operators, not scalable (scene updates)
        O.object.mode_set(mode='EDIT')
        O.mesh.select_all(action='SELECT')
        # O.mesh.remove_doubles(threshold=0.0001)
        O.mesh.tris_convert_to_quads(face_threshold=3.14159, shape_threshold=3.14159)
        O.object.mode_set(mode='OBJECT')

    def create_mesh(data):
        """
        Takes all the data gathered and generates a mesh, deals with custom normals and applies materials.
        Args:
            data ('dict') - The json mesh data: vertices, normals, coordinates, faces and material references.
        Returns:
            me ('bpy.types.')
        """
        # FIXME Renaming for readability and clarity
        # FIXME take rotDeg and position of MESH into account (?)
        verts_loc = data['verts_loc']
        verts_nor = data['verts_nor']
        verts_uvs = data['verts_uvs'] if 'verts_uvs' in data else []
        verts_uvs2 = data['verts_uvs2'] if 'verts_uvs2' in data else []

        faces = data['faces']

        total_loops = len(faces)*3

        loops_vert_idx = []
        faces_loop_start = []
        faces_loop_total = [] # we can assume that, since all faces are trigons
        l_idx = 0 #loop index = ?? count for assigning loop start index to face

        # FIXME Document properly in the wiki and maybe also for external publishing
        # FIXME simplify fixed values
        for f in faces:
            v_idx = f[0] # The vertex indices of this face [a, b , c]
            nbr_vidx = 3 # len(v_idx) Vertices count per face (Always 3 (all faces are trigons))

            loops_vert_idx.extend(v_idx) # Append all vert idx to loops vert idx
            faces_loop_start.append(l_idx)

            faces_loop_total.append(nbr_vidx) # (list of [3, 3, 3 ... ] vertex idc count per face)
            l_idx += nbr_vidx # Add the count to the total count to get the loop_start for the next face

        # Create a new mesh
        me = bpy.data.meshes.new(data['name'])
        # Add new empty vertices and polygons to the mesh
        me.vertices.add(len(verts_loc))
        me.loops.add(total_loops)
        me.polygons.add(len(faces))

        # Note unpack_list creates a flat array
        me.vertices.foreach_set('co', unpack_list(verts_loc))
        me.loops.foreach_set('vertex_index', loops_vert_idx)
        me.polygons.foreach_set('loop_start', faces_loop_start)
        me.polygons.foreach_set('loop_total', faces_loop_total)

        # Empty split vertex normals
        # Research: uvs not correct if split normals are set below blen_layer
        # Note: we store 'temp' normals in loops, since validate() may alter final mesh,
        #       we can only set custom loop_nors *after* calling it.
        me.create_normals_split()

        if verts_uvs:
            # FIXME: Research: difference between uv_layers and uv_textures (get layer directly?)
            me.uv_textures.new(name='UVMap')
            blen_uvs = me.uv_layers['UVMap']

        if verts_uvs2:
            me.uv_textures.new(name='UVLightmap')
            blen_uvs2 = me.uv_layers['UVLightmap']

        # FIXME validate before applying vertex normals

        # Loop trough tuples of corresponding face / polygon
        for i, (face, blen_poly) in enumerate(zip(faces, me.polygons)):
            (face_vert_loc_indices,
             face_vert_nor_indices,
             face_vert_uvs_indices,
             face_vert_uvs2_indices) = face

            for face_nor_idx, loop_idx in zip(face_vert_nor_indices, blen_poly.loop_indices):
                # FIXME Understand ... ellipsis (verts_nor[0 if (face_noidx is ...) else face_noidx])
                me.loops[loop_idx].normal[:] = verts_nor[face_nor_idx]

            if verts_uvs:
                for face_uvs_idx, loop_idx in zip(face_vert_uvs_indices, blen_poly.loop_indices):
                    blen_uvs.data[loop_idx].uv = verts_uvs[face_uvs_idx]
            if verts_uvs2:
                for face_uvs2_idx, loop_idx in zip(face_vert_uvs2_indices, blen_poly.loop_indices):
                    blen_uvs2.data[loop_idx].uv = verts_uvs2[face_uvs2_idx]

        me.validate(clean_customdata=False)
        me.update()

        # if normals
        cl_nors = array.array('f', [0.0] * (len(me.loops) * 3)) # Custom loop normals
        me.loops.foreach_get('normal', cl_nors)

        nor_split_set = tuple(zip(*(iter(cl_nors),) * 3))
        me.normals_split_custom_set(nor_split_set) # float array of 3 items in [-1, 1]
        # FIXME check if these steps are necessary and what they actually do
        # Set use_smooth -> actually this automatically calculates the median between two custom normals (if connected)
        # This feature could be nice if they share the
        # me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
        me.use_auto_smooth = True
        return me

    def join_objects(group):
        """ Joins all objects of the group
            Args:
                group ('bpy_prop_collection') - Objects to be joined.
            Returns:
                joined_object ('bpy_types.Object') - The joined object.
        """

        # If there are objects in the object group, join them
        if len(group) > 0:
            select(group, discard_selection=True)

            # Join them into the first object return the resulting object
            C.scene.objects.active = group[0]
            O.object.mode_set(mode='OBJECT')
            joined = group[0]

            if O.object:
                O.object.join()
            return joined

        else:
            log.debug('No objects to join.')
            return None

    def select(objects, discard_selection=True):
        """ Select all objects in this group.
            Args:
                objects ('bpy_types.Object', 'bpy_prop_collection') - Object(s) to be selected
            Kwargs:
                discard_selection ('bool') - Discard original selection (Default=True)
        """
        group = []
        if hasattr(objects, '__iter__'):
            group = objects
        else:
            group.append(objects)

        if discard_selection:
            O.object.select_all(action='DESELECT')

        for obj in group:
            obj.select = True
            C.scene.objects.active = obj

    def normalise_objects(objects, apply_location=False):
        """ Prepare object for baking/export, apply transform
            Args:
                objects ('bpy_types.Object', 'bpy_prop_collection') - Object(s) to be normalised.
            Kwargs:
                apply_location ('boolean') - Apply location of the object.
        """
        group = []

        if hasattr(objects, '__iter__'):
            for obj in objects:
                if obj is None and obj.type != 'MESH':
                    group.append(obj)
        else:
            group.append(objects)

        select(group, discard_selection=True)
        O.object.transform_apply(location=apply_location, rotation=True, scale=True)

    try:
        t0 = time.perf_counter()

        # Import mesh-materials
        bl_materials = {}
        if import_materials:
            bl_materials = import_data3d_materials(data3d_objects, filepath, kwargs['import_al_metadata'])
            perf_times['material_import'] = time.perf_counter() - t0
        t1 = time.perf_counter()

        for data3d_object in data3d_objects:
            # Import meshes as bl_objects
            al_meshes = data3d_object.meshes
            bl_meshes = []
            bl_emission_meshes = []

            for al_mesh in al_meshes:
                # Create mesh and add it to an object.
                bl_mesh = create_mesh(al_mesh)
                ob = D.objects.new(al_mesh['name'], bl_mesh)
                is_emissive = False
                if import_materials:
                    # Apply the material to the mesh.
                    if D3D.m_material in al_mesh:
                        original_key = al_mesh[D3D.m_material]
                        mat_hash_map = data3d_object.mat_hash_map
                        if original_key:
                            hashed_key = mat_hash_map[original_key] if original_key in mat_hash_map else ''
                            if hashed_key and hashed_key in bl_materials:
                                mat = bl_materials[hashed_key]
                                ob.data.materials.append(mat.bl_material)
                                if mat.get_al_mat_node(D3D.coef_emit, fallback=0.0) > 0.0:
                                    is_emissive = True
                            else:
                                raise Exception('Material not found: ' + hashed_key)
                    else:
                        if D3D.mat_default in D.materials:
                            ob.data.materials.append(D.materials[D3D.mat_default])
                        else:
                            ob.data.materials.append(D.materials.new(D3D.mat_default))

                # Link the object to the scene and clean it for further use.
                C.scene.objects.link(ob)
                optimize_mesh(ob)
                if is_emissive:
                    bl_emission_meshes.append(ob)
                else:
                    bl_meshes.append(ob)

            # WORKAROUND: we are joining all objects instead of joining generated mesh (bmesh module would support this)
            if len(bl_meshes) > 0:
                joined_object = join_objects(bl_meshes)
                joined_object.name = data3d_object.node_id
                data3d_object.set_bl_object(joined_object)
            else:
                ob = D.objects.new(data3d_object.node_id, None)
                C.scene.objects.link(ob)
                data3d_object.set_bl_object(ob)

            if len(bl_emission_meshes) > 0:
                joined_object = join_objects(bl_emission_meshes)
                joined_object.name = data3d_object.node_id + '_emission'
                # Make object invisible for camera & shadow ray
                joined_object.cycles_visibility.shadow = False
                joined_object.cycles_visibility.camera = False
                data3d_object.set_bl_emission_object(joined_object)

            # Relative rotation and position to the parent
            data3d_object.bl_object.location = data3d_object.position
            data3d_object.bl_object.rotation_euler = data3d_object.rotation


        # Make parent - children relationships
        bl_root_objects = []
        for data3d_object in data3d_objects:
            parent = data3d_object.parent
            if parent:
                data3d_object.bl_object.parent = parent.bl_object
                if data3d_object.bl_emission_object:
                    data3d_object.bl_emission_object.parent = parent.bl_object
            else:
                bl_root_objects.append(data3d_object.bl_object)
                if data3d_object.bl_emission_object:
                    bl_root_objects.append(data3d_object.bl_emission_object)

        t2 = time.perf_counter()
        perf_times['mesh_import'] = t2 - t1

        # Apply the global matrix
        normalise_objects(bl_root_objects, apply_location=True)
        for obj in bl_root_objects:
            obj.matrix_world = global_matrix

        if import_hierarchy:
            for data3d_object in data3d_objects:
                bl_object = data3d_object.bl_object
                if bl_object.type == 'EMPTY' and not data3d_object.children:
                    C.scene.objects.unlink(bl_object)
                    D.objects.remove(bl_object)

        else:
            bl_objects = [o.bl_object for o in data3d_objects]

            # Clear the parent-child relationships, keep transform
            # FIXME operation is really slow. find option to do this via datablock (parent_clear /transform_apply)
            for bl_object in bl_objects:
                select(bl_object, discard_selection=False)
                O.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

            normalise_objects(bl_objects, apply_location=True)

            for bl_object in bl_objects:
                if bl_object.type == 'EMPTY':
                    C.scene.objects.unlink(bl_object)
                    D.objects.remove(bl_object)
             # FIXME Hierarchy cleanup is extremely costly. maybe we can keep the hierarchy for the bakes?
            t3 = time.perf_counter()
            perf_times['cleanup'] = t3 - t2

        return perf_times

    except:
        raise Exception('Import Scene failed. ', sys.exc_info())


def create_metrics(times):
    log.info('\n\n{}'
             '\n\nImport Data3d successful.'
             '\n\n{}: Total'
             '\n\n{}: Deserialization of data'
             '\n\n{}: Material import'
             '\n\n{}: Mesh import'
             '\n\n{}: Flatten hierarchy'
             '\n\n{}\n\n'.format(60*'#',
                                 '%.2f' % times['total'],
                                 '%.2f' % times['deserialization'],
                                 '%.2f' % times['material_import'] if 'material_import' in times else 'None',
                                 '%.2f' % times['mesh_import'],
                                 '%.2f' % times['cleanup'] if 'cleanup' in times else 'None',
                                 60*'#'))


########
# Main #
########


def load(**args):
    """ Called by the user interface or another script.
        Kwargs:
            filepath ('str') - The filepath to the data3d source file.
            import_materials ('bool') - Import and apply materials.
            import_hierarchy ('bool') - Import and keep the parent-child hierarchy.
            import_al_metadata ('bool') - Import the Archilogic data as metadata.
            global_matrix ('Matrix') - The global orientation matrix to apply.
    """
    if args['config_logger']:
        logging.basicConfig(level='DEBUG', format='%(asctime)s %(levelname)-10s %(message)s', stream=sys.stdout)

    log.info('Data3d import started, %s', args)
    t0 = time.perf_counter()

    if args['global_matrix']is None:
        args['global_matrix'] = mathutils.Matrix()

    # FIXME try-except
    # try:
    # Import the file - Json dictionary
    input_file = args['filepath']
    from_buffer = True if input_file.endswith('.data3d.buffer') else False
    log.info('File format is buffer: %s', from_buffer)
    data3d_objects, meta = deserialize_data3d(input_file, from_buffer=from_buffer)

    t1 = time.perf_counter()

    perf_times = import_scene(data3d_objects, **args)

    C.scene.update()

    t2 = time.perf_counter()
    perf_times['deserialization'] = t1-t0
    perf_times['total'] = t2-t0
    create_metrics(perf_times)

    return {'FINISHED'}

    # except:
    #     FIXME clean scene from created data-blocks
    #     print('Data3d import failed: ', sys.exc_info())
    #     return {'CANCELLED'}

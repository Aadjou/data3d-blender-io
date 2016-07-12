import os
import logging

import bpy
from bpy_extras.image_utils import load_image

from io_scene_data3d.data3d_utils import D3D

# Global Variables
C = bpy.context
D = bpy.data
O = bpy.ops

logging.basicConfig(level='DEBUG', format='%(asctime)s %(levelname)-10s %(message)s')
log = logging.getLogger('archilogic')


class Material:
    """
        Attributes:
            al_material_hash
            al_material
            bl_material
    """

    def __init__(self, key, al_material, import_metadata, working_dir):
        """ Return a Material object. Import data3d materials and translate them to Blender Internal & Cycles materials
        Args:
            key ('str') - The hashed material key. Used for naming the material.
            al_material ('dict') - The data3d Material source.
            import_metadata ('bool') - Import the data3d Material json as Blender material metadata.
            working_dir ('str') - The source directory of the data3d file, used for recursive image search.
        """
        self.al_material = al_material
        self.al_material_hash = key
        self.import_metadata = import_metadata
        self.bl_material = D.materials.new(key)

        # Create Blender Material
        create_blender_material(self.al_material, self.bl_material, working_dir, import_metadata)

        # Create Cycles Material
        create_cycles_material(self.al_material, self.bl_material, working_dir)

    # def get_bl_material(self):
    #     if self.bl_material:
    #         return self.bl_material
    #     else:
    #         # Create Blender Material
    #         self.bl_material = create_blender_material(self.al_material, self.working_directory, self.import_metadata)
    #         # Create Cycles Material
    #         create_cycles_material(self.al_material, self.bl_material, self.working_directory)

    def get_al_mat_node(self, key):
        if key in self.al_material:
            return self.al_material[key]
        else:
            return None


def create_blender_material(al_mat, bl_mat, working_dir, import_metadata):
    """ Create the blender material
        Args:
            al_mat ('dict') - The data3d Material source.
            bl_mat ('bpy.types.Material') - The Blender Material datablock.
            working_dir ('str') - The source directory of the data3d file, used for recursive image search.
            import_metadata ('bool') - Import the data3d Material json as Blender material metadata.
    """
    # Override default material settings
    bl_mat.use_fake_user = True
    bl_mat.diffuse_intensity = 1
    bl_mat.specular_intensity = 1

     # Import Archilogic Material Datablock (FIXME check PropertyGroup)
    if import_metadata:
        bl_mat['Data3d Material'] = al_mat

    if D3D.col_diff in al_mat:
        bl_mat.diffuse_color = al_mat[D3D.col_diff]
    else:
        bl_mat.diffuse_color = (0.85,)*3
    if D3D.col_spec in al_mat:
        bl_mat.specular_color = al_mat[D3D.col_spec]
    else:
        bl_mat.diffuse_color = (0.25,)*3
    if D3D.coef_spec in al_mat:
        bl_mat.specular_hardness = int(al_mat[D3D.coef_spec])
    else:
        bl_mat.specular_hardness = 1
    if D3D.coef_emit in al_mat:
        bl_mat.emit = float(al_mat[D3D.coef_emit])
    if D3D.opacity in al_mat:
        opacity = al_mat[D3D.opacity]
        if opacity < 1:
            bl_mat.use_transparency = True
            bl_mat.transparency_method = 'Z_TRANSPARENCY'
            bl_mat.alpha = opacity

    ref_maps = get_reference_maps(al_mat)
    for map_key in ref_maps:
        set_image_texture(bl_mat, ref_maps[map_key], map_key, working_dir)

    if D3D.uv_scale in al_mat:
        scale = al_mat[D3D.uv_scale]
        for tex_slot in bl_mat.texture_slots:
            if tex_slot is not None:
                tex_slot.scale[0] = 1/scale[0]
                tex_slot.scale[1] = 1/scale[1]


def create_cycles_material(al_mat, bl_mat, working_dir):
    """ Create the cycles material
        Args:
            al_mat ('dict') - The data3d Material source.
            bl_mat ('bpy.types.Material') - The Blender Material datablock.
            working_dir ('str') - The source directory of the data3d file, used for recursive image search.
    """
    # This dict translates between node input names and d3d keys. (This prevents updates in the library.blend file)
    d3d_to_node = {
        D3D.map_diff: 'map-diffuse',
        D3D.map_spec: 'map-specular',
        D3D.map_norm: 'map-normal',
        D3D.map_alpha: 'map-alpha',
        D3D.map_light: '',
        D3D.col_diff: 'color-diffuse',
        D3D.col_spec: 'color-specular',
        D3D.coef_spec: 'specular-intensity',
        D3D.coef_emit: 'emission-intensity',
        D3D.opacity: 'opacity',
    }

    # Setup Cycles Material and remove all nodes.
    C.scene.render.engine = 'CYCLES'
    bl_mat.use_nodes = True
    node_tree = bl_mat.node_tree
    for node in node_tree.nodes:
        node_tree.nodes.remove(node)

    # Material group node (The datablock is not yet assigned)
    node_group = node_tree.nodes.new('ShaderNodeGroup')
    node_group.location = (0, 0)

    # Distinguish between tree different Material types.
    # Adaptations to the nodes: node_library.blend file.
    # Basic Material (diffuse & glossy Shader) supports standard maps, fallback on neutral inputs.
    # Emission Material (emission & transparent shader) supports diffuse and alpha maps, diffuse color as emit color.
    # Transparent Material (transparent Shader) supports alpha maps and opacity additional to the basic material.

    opacity = al_mat[D3D.opacity] if D3D.opacity in al_mat else 1.0
    emission = al_mat[D3D.coef_emit] if D3D.coef_emit in al_mat else 0.0
    if emission > 0.0:
        log.debug('emission material')
        node_group.node_tree = D.node_groups['archilogic-emission']

    elif D3D.map_alpha in al_mat or opacity < 1.0:
        log.debug('advanced: transparency material')
        node_group.node_tree = D.node_groups['archilogic-transparency']

    #elif FIXME Add Cycles Lightmap support

    else:
        log.debug('basic material %s', al_mat)
        # Add the corresponding Material node group ('archilogic-basic')
        node_group.node_tree = D.node_groups['archilogic-basic']

    # Material Output Node
    output_node = node_tree.nodes.new('ShaderNodeOutputMaterial')
    output_node.location = (200, 0)
    # Link the group shader to the output_node
    node_tree.links.new(node_group.outputs['Shader'], output_node.inputs['Surface'])

    # Textures
    # Get the texture reference maps
    ref_maps = get_reference_maps(al_mat)

    # UV Map and UV Scale node
    uv_map_node = None
    uv2_map_node = None
    uv_scale_node = None

    if ref_maps:
        has_lightmap = D3D.map_light in ref_maps

        if has_lightmap is False or (has_lightmap and len(ref_maps) > 1):
            uv_map_node = node_tree.nodes.new('ShaderNodeUVMap')
            uv_map_node.uv_map = 'UVMap'
            uv_map_node.location = (-800, 0)
            uv_scale_node = node_tree.nodes.new('ShaderNodeMapping')
            uv_scale_node.vector_type = 'TEXTURE'
            uv_scale_node.scale = al_mat[D3D.uv_scale] + (1, ) if D3D.uv_scale in al_mat else (1, )*3
            uv_scale_node.location = (-600, 0)
            node_tree.links.new(uv_map_node.outputs['UV'], uv_scale_node.inputs['Vector'])

        if has_lightmap:
            uv2_map_node = node_tree.nodes.new('ShaderNodeUVMap')
            uv2_map_node.uv_map = 'UVLightmap'

    # Create texture map nodes
    count = 0
    for map_key in ref_maps:
        if d3d_to_node[map_key] in node_group.inputs:
            count += 1
            map_node = node_tree.nodes.new('ShaderNodeTexImage')
            map_node.image = get_image_datablock(ref_maps[map_key], working_dir, recursive=True)
            map_node.label = map_key
            # Connect the nodes
            if uv_scale_node:
                node_tree.links.new(uv_scale_node.outputs['Vector'], map_node.inputs['Vector'])
            node_tree.links.new(map_node.outputs['Color'], node_group.inputs[d3d_to_node[map_key]])
            # Position the nodes
            x = int(count / 2) * -300 if count % 2 else int(count / 2) * 300
            map_node.location = (-200, x)

        elif map_key is D3D.map_light:
            map_node = node_tree.nodes.new('ShaderNodeTexImage')
            map_node.image = get_image_datablock(ref_maps[map_key], working_dir, recursive=True)
            map_node.label = map_key
            emission_node = node_tree.nodes.new('ShaderNodeEmission')
            add_shader_node = node_tree.nodes.new('ShaderNodeAddShader')

            node_tree.links.new(uv2_map_node.outputs['UV'], map_node.inputs['Vector'])
            node_tree.links.new(map_node.outputs['Color'], emission_node.inputs['Color'])
            node_tree.links.new(map_node.outputs['Color'], emission_node.inputs['Strength'])
            node_tree.links.new(node_group.outputs['Shader'], add_shader_node.inputs[0])
            node_tree.links.new(emission_node.outputs['Emission'], add_shader_node.inputs[1])
            node_tree.links.new(add_shader_node.outputs['Shader'], output_node.inputs['Surface'])

            # Position the nodes
            uv2_map_node.location = (-800, 600)
            map_node.location = (-200, 600)
            emission_node.location = (-0, 600)
            add_shader_node.location = (200, 0)
            output_node.location = (400, 0)


    if D3D.col_diff in al_mat and d3d_to_node[D3D.col_diff] in node_group.inputs:
        node_group.inputs[d3d_to_node[D3D.col_diff]].default_value = al_mat[D3D.col_diff] + (1, )

    if D3D.col_spec in al_mat and d3d_to_node[D3D.col_spec] in node_group.inputs:
        node_group.inputs[d3d_to_node[D3D.col_spec]].default_value = al_mat[D3D.col_spec] + (1, )

    if D3D.coef_spec in al_mat and d3d_to_node[D3D.coef_spec] in node_group.inputs:
        node_group.inputs[d3d_to_node[D3D.coef_spec]].default_value = min(max(0.0, al_mat[D3D.coef_spec]), 100.0)

    if D3D.coef_emit in al_mat and d3d_to_node[D3D.coef_emit] in node_group.inputs:
        node_group.inputs[d3d_to_node[D3D.coef_emit]].default_value = min(max(0.0, al_mat[D3D.coef_emit]), 100.0)

    if D3D.opacity in al_mat and d3d_to_node[D3D.opacity] in node_group.inputs:
        node_group.inputs[d3d_to_node[D3D.opacity]].default_value = al_mat[D3D.opacity]


def get_reference_maps(al_mat):
    """ Get all the texture maps and find the source image with the best quality.
        Args:
            al_mat ('dict') - The data3d Material source.
        Returns:
            ref_maps ('dict') - The reference maps.
    """
    map_types = [D3D.map_diff, D3D.map_spec, D3D.map_norm, D3D.map_alpha, D3D.map_light]
    ref_maps = {}
    for map_key in map_types:
        map_key_source = map_key + D3D.map_suffix_source
        map_key_preview = map_key + D3D.map_suffix_preview

        maps = [
            al_mat[map_key_source] if map_key_source in al_mat else '',
            al_mat[map_key] if map_key in al_mat else '',
            al_mat[map_key_preview] if map_key_preview in al_mat else ''
        ]
        ref_map = next((m for m in maps if (m and not m.endswith('.dds'))), '')
        if ref_map:
            ref_maps[map_key] = ref_map
    return ref_maps


def set_image_texture(bl_mat, image_path, map_key, working_dir):
    """ Set the texture references for the Blender Internal material
        Args:
            bl_mat ('bpy.types.Material') - The Blender Material datablock.
            map_key ('str') - The map key.
            working_dir ('str') - The source directory of the data3d file, used for recursive image search.
    """

    # Create the blender image texture
    name = map_key + '-' + os.path.splitext(os.path.basename(image_path))[0]
    texture = bpy.data.textures.new(name=name, type='IMAGE')
    texture.use_fake_user = True
    image = get_image_datablock(image_path, working_dir, recursive=True)

    texture.image = image
    tex_slot = bl_mat.texture_slots.add()
    tex_slot.texture_coords = 'UV'
    tex_slot.texture = texture
    tex_slot.use_map_color_diffuse = False

    if map_key == D3D.map_diff:
        tex_slot.use_map_color_diffuse = True
    elif map_key == D3D.map_norm:
        texture.use_normal_map = True
        tex_slot.use_map_normal = True
    elif map_key == D3D.map_spec:
        texture.use_normal_map = True
        tex_slot.use_map_specular = True
    elif map_key == D3D.map_alpha:
        texture.use_normal_map = True
        tex_slot.use_map_alpha = True
        bl_mat.use_transparency = True
        bl_mat.transparency_method = 'Z_TRANSPARENCY'
    elif map_key == D3D.map_light:
        tex_slot.uv_layer = 'UVLightmap'
        tex_slot.use_map_emit = True
        tex_slot.use_rgb_to_intensity = True
    else:
        log.error('Image Texture type not found, %s', map_key)


def get_image_datablock(image_relpath, image_directory, recursive=False):
    """ Load the image to blender, check if image has been loaded before.
        Args:
            image_relpath ('str') - The relative path to the image.
            image_directory ('str') - The parent directory.
            recursive ('bool') - Use recursive image search.
        Returns:
            img ('bpy.types.Image') - The loaded image datablock.
    """
    # FIXME: make use image search optional
    image_directory = os.path.normpath(image_directory)
    img = load_image(image_relpath, dirname=image_directory, recursive=recursive, check_existing=True)
    if img is None:
        # FIXME: Failed to load images report for automated baking
        log.warning('Warning: Image could not be loaded: %s in directory %s ', image_relpath, dir)
        return None
    img.use_fake_user = True
    return img


def import_material_node_groups():
    """ Load the archilogic cycles material node groups from the node-library.blend file.
    """
    filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'node-library.blend')

    with bpy.data.libraries.load(filepath) as (data_from, data_to):
        data_to.node_groups = data_from.node_groups

    for node_group in data_to.node_groups:
        log.debug('Importing material node group: %s', node_group.name)
        node_group.use_fake_user = True


#################
# Setup         #
#################

def setup():
    """ Setup the material utils, load node groups.
    """
    # Import the Cycles material node groups from reference file
    log.info('Setting up material_utils.')
    import_material_node_groups()

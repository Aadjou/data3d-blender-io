# coding=utf-8
bl_info = {
    "name": "Archilogic I/O data3d format",
    "author": "Madlaina Kalunder",
    "version": (0, 1),
    "blender": (2, 77, 0),
    "location": "File > import-export",
    "description": "Import-Export Archilogic Data3d format, "
                   "materials and textures",
    "warning": "Add-on is in development.",
    "wiki_url": "",
    "category": "Import-Export"
}

if "bpy" in locals():
    import importlib
    if "import_data3d" in locals():
        importlib.reload(import_data3d)
    if "export_data3d" in locals():
        importlib.reload(export_data3d)

import bpy
from bpy.props import (
        BoolProperty,
        FloatProperty,
        StringProperty,
        EnumProperty
        )

from bpy_extras.io_utils import (
        ImportHelper,
        ExportHelper,
        axis_conversion,
        orientation_helper_factory
        )


class ModuleInfo:
    add_on_version = '.'.join([str(item) for item in bl_info['version']])
    data3d_format_version = '1'

IOData3dOrientationHelper = orientation_helper_factory('IOData3dOrientationHelper', axis_forward='-Z', axis_up='Y')


class ImportData3d(bpy.types.Operator, ImportHelper, IOData3dOrientationHelper):
    """ Load a Archilogic Data3d File """

    bl_idname = 'import_scene.data3d'
    bl_label = 'Import Data3d'
    bl_options = {'PRESET', 'UNDO'}

    filter_glob = StringProperty(default='*.data3d.buffer;*.data3d.json', options={'HIDDEN'})

    import_materials = BoolProperty(
        name='Import Materials',
        description='Import Materials and Textures.',
        default=True
        )

    import_hierarchy = BoolProperty(
        name='Import Hierarchy',
        description='Import objects with parent-child relations.',
        default=True
        )

    # Hidden context
    import_al_metadata = BoolProperty(
        name='Import Archilogic Metadata',
        description='Import Archilogic Metadata',
        default=False
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'import_materials')
        layout.prop(self, 'import_hierarchy')

        #Fixme Import materials (bool) if yes -> import cycles, import blender, use image search?

        layout.prop(self, "axis_forward")
        layout.prop(self, "axis_up")

    def execute(self, context):
        from . import import_data3d
        keywords = self.as_keywords(ignore=('axis_forward',
                                            'axis_up',
                                            'filter_glob'))
        keywords['global_matrix'] = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up).to_4x4()
        return import_data3d.load(**keywords)


class ExportData3d(bpy.types.Operator, ExportHelper, IOData3dOrientationHelper):
    """ Export the scene as an Archilogic Data3d File """

    # export_materials
    # export_textures
    # apply modifiers

    bl_idname = 'export_scene.data3d'
    bl_label = 'Export Data3d'
    bl_options = {'PRESET'}

    filename_ext = '.data3d.json'
    filter_glob = StringProperty(default='*.data3d.buffer;*.data3d.json', options={'HIDDEN'})

    # Context
    export_mode = EnumProperty(
        name='Mode',
        description='Export geometry interleaved(buffer) or non-interleaved (json).',
        default='INTERLEAVED',
        items=[
            ('INTERLEAVED', 'interleaved', '', 0),
            ('NON_INTERLEAVED', 'non-interleaved', '', 1)
            ]
    )

    use_selection = BoolProperty(
        name='Selection Only',
        description='Export selected objects only.',
        default=False
    )

    export_images = BoolProperty(
        name='Export Images',
        description='Export associated texture files.',
        default=False
    )

    # Hidden context
    export_al_metadata = BoolProperty(
        name='Export Archilogic Metadata',
        description='Export Archilogic Metadata, if it exists.',
        default=False
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'export_mode')
        layout.prop(self, 'use_selection')
        layout.prop(self, 'export_images')

    def execute(self, context):
        from . import export_data3d

        keywords = self.as_keywords(ignore=('axis_forward',
                                            'axis_up',
                                            'filter_glob',
                                            'filename_ext',
                                            'check_existing'))
        global_matrix = axis_conversion(to_forward=self.axis_forward,
                                        to_up=self.axis_up,
                                        ).to_4x4()
        keywords["global_matrix"] = global_matrix
        return export_data3d.save(context, **keywords)


# Fixme create convert bl to cycles operator, similar to ml converter addon
class ToggleEngine(bpy.types.Operator):
    bl_idname = 'al.toggle'
    bl_label = 'Toggle render engine.'
    bl_description = 'Toggle render engine.'
    bl_register = True
    bl_undo = True

    # @classmethod
    # def poll(cls, context):
    #     return True

    def execute(self, context):
        from . import material_utils
        material_utils.toggle_render_engine()
        return {'FINISHED'}


class MATERIAL_PT_data3d(bpy.types.Panel):
    bl_label = "Data3d Material Utils"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        box = row.box()
        box.operator('al.toggle', text='Toggle Render Engine', icon='FILE_REFRESH')



def menu_func_import(self, context):
    self.layout.operator(ImportData3d.bl_idname, text='Archilogic Data3d (data3d.buffer/data3d.json)')


def menu_func_export(self, context):
    self.layout.operator(ExportData3d.bl_idname, text='Archilogic Data3d (data3d.buffer/data3d.json)')


def register():
    bpy.utils.register_module(__name__)
    bpy.types.INFO_MT_file_import.append(menu_func_import)
    bpy.types.INFO_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_module(__name__)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)
    bpy.types.INFO_MT_file_export.remove(menu_func_export)


if __name__ == '__main__':
    register()
import os
import pickle

from dagster import check
from dagster.config import Field
from dagster.config.source import StringSource
from dagster.core.definitions.events import AssetKey, AssetMaterialization, EventMetadataEntry
from dagster.core.execution.context.system import InputContext, OutputContext
from dagster.core.storage.io_manager import IOManager, io_manager
from dagster.utils import PICKLE_PROTOCOL, mkdir_p
from dagster.utils.backcompat import experimental


@io_manager(config_schema={"base_dir": Field(StringSource, default_value=".", is_required=False)})
def fs_io_manager(init_context):
    """Built-in filesystem IO manager that stores and retrieves values using pickling.

    It allows users to specify a base directory where all the step outputs will be stored. It
    serializes and deserializes output values using pickling and automatically constructs
    the filepaths for the assets.

    Example usage:

    1. Specify a pipeline-level IO manager using the reserved resource key ``"io_manager"``,
    which will set the given IO manager on all solids across a pipeline.

    .. code-block:: python

        @solid
        def solid_a(context, df):
            return df

        @solid
        def solid_b(context, df):
            return df[:5]

        @pipeline(mode_defs=[ModeDefinition(resource_defs={"io_manager": fs_io_manager})])
        def pipe():
            solid_b(solid_a())


    2. Specify IO manager on :py:class:`OutputDefinition`, which allows the user to set
    different IO managers on different step outputs.

    .. code-block:: python

        @solid(output_defs=[OutputDefinition(io_manager_key="my_io_manager")])
        def solid_a(context, df):
            return df

        @solid
        def solid_b(context, df):
            return df[:5]

        @pipeline(
            mode_defs=[ModeDefinition(resource_defs={"my_io_manager": fs_io_manager})]
        )
        def pipe():
            solid_b(solid_a())

    """

    return PickledObjectFilesystemIOManager(init_context.resource_config["base_dir"])


class PickledObjectFilesystemIOManager(IOManager):
    """Built-in filesystem IO manager that stores and retrieves values using pickling.

    Args:
        base_dir (Optional[str]): base directory where all the step outputs which use this object
            manager will be stored in.
    """

    def __init__(self, base_dir=None):
        self.base_dir = check.opt_str_param(base_dir, "base_dir")
        self.write_mode = "wb"
        self.read_mode = "rb"

    def _get_path(self, context):
        """Automatically construct filepath."""
        keys = context.get_run_scoped_output_identifier()

        return os.path.join(self.base_dir, *keys)

    def handle_output(self, context, obj):
        """Pickle the data and store the object to a file.

        This method omits the AssetMaterialization event so assets generated by it won't be tracked
        by the Asset Catalog.
        """
        check.inst_param(context, "context", OutputContext)

        filepath = self._get_path(context)
        context.log.debug(f"Writing file at: {filepath}")

        # Ensure path exists
        mkdir_p(os.path.dirname(filepath))

        with open(filepath, self.write_mode) as write_obj:
            pickle.dump(obj, write_obj, PICKLE_PROTOCOL)

    def load_input(self, context):
        """Unpickle the file and Load it to a data object."""
        check.inst_param(context, "context", InputContext)

        filepath = self._get_path(context.upstream_output)
        context.log.debug(f"Loading file from: {filepath}")

        with open(filepath, self.read_mode) as read_obj:
            return pickle.load(read_obj)


class CustomPathPickledObjectFilesystemIOManager(IOManager):
    """Built-in filesystem IO managerthat stores and retrieves values using pickling and
    allow users to specify file path for outputs.

    Args:
        base_dir (Optional[str]): base directory where all the step outputs which use this object
            manager will be stored in.
    """

    def __init__(self, base_dir=None):
        self.base_dir = check.opt_str_param(base_dir, "base_dir")
        self.write_mode = "wb"
        self.read_mode = "rb"

    def _get_path(self, path):
        return os.path.join(self.base_dir, path)

    def handle_output(self, context, obj):
        """Pickle the data and store the object to a custom file path.

        This method emits an AssetMaterialization event so the assets will be tracked by the
        Asset Catalog.
        """
        check.inst_param(context, "context", OutputContext)
        metadata = context.metadata
        path = check.str_param(metadata.get("path"), "metadata.path")

        filepath = self._get_path(path)

        # Ensure path exists
        mkdir_p(os.path.dirname(filepath))
        context.log.debug(f"Writing file at: {filepath}")

        with open(filepath, self.write_mode) as write_obj:
            pickle.dump(obj, write_obj, PICKLE_PROTOCOL)

        return AssetMaterialization(
            asset_key=AssetKey([context.pipeline_name, context.step_key, context.name]),
            metadata_entries=[EventMetadataEntry.fspath(os.path.abspath(filepath))],
        )

    def load_input(self, context):
        """Unpickle the file from a given file path and Load it to a data object."""
        check.inst_param(context, "context", InputContext)
        metadata = context.upstream_output.metadata
        path = check.str_param(metadata.get("path"), "metadata.path")
        filepath = self._get_path(path)
        context.log.debug(f"Loading file from: {filepath}")

        with open(filepath, self.read_mode) as read_obj:
            return pickle.load(read_obj)


@io_manager(config_schema={"base_dir": Field(StringSource, default_value=".", is_required=False)})
@experimental
def custom_path_fs_io_manager(init_context):
    """Built-in IO manager that allows users to custom output file path per output definition.

    It also allows users to specify a base directory where all the step output will be stored in. It
    serializes and deserializes output values (assets) using pickling and stores the pickled object
    in the user-provided file paths.

    Example usage:

    .. code-block:: python

        @solid(
            output_defs=[
                OutputDefinition(
                    io_manager_key="io_manager", metadata={"path": "path/to/sample_output"}
                )
            ]
        )
        def sample_data(context, df):
            return df[:5]

        @pipeline(
            mode_defs=[
                ModeDefinition(resource_defs={"io_manager": custom_path_fs_io_manager}),
            ],
        )
        def pipe():
            sample_data()
    """
    return CustomPathPickledObjectFilesystemIOManager(init_context.resource_config["base_dir"])

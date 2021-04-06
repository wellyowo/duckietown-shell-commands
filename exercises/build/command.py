import argparse
import os
import traceback

import yaml
from dt_shell import DTCommandAbs, DTShell, dtslogger, UserError
from dt_shell.env_checks import check_docker_environment

from utils.cli_utils import start_command_in_subprocess
from utils.docker_utils import pull_if_not_exist, remove_if_running

usage = """

## Basic usage
    This is a helper for the exercises. 
    You must run this command inside an exercise folder. 

    To know more on the `exercise` commands, use `dts duckiebot exercise -h`.

        $ dts exercise build 

"""

BRANCH = "daffy"
ARCH = "amd64"
AIDO_REGISTRY = "registry-stage.duckietown.org"
ROS_TEMPLATE_IMAGE = "duckietown/challenge-aido_lf-template-ros:" + BRANCH + "-" + ARCH
CF = "config.yaml"


class InvalidUserInput(UserError):
    pass


class DTCommand(DTCommandAbs):
    @staticmethod
    def command(shell: DTShell, args):
        prog = "dts exercise build"
        parser = argparse.ArgumentParser(prog=prog, usage=usage)

        parser.add_argument(
            "--staging",
            "-t",
            dest="staging",
            action="store_true",
            default=False,
            help="Should we use the staging AIDO registry?",
        )

        parser.add_argument(
            "--debug",
            "-d",
            dest="debug",
            action="store_true",
            default=False,
            help="Will give you a terminal inside the container",
        )

        parser.add_argument(
            "--clean",
            "-c",
            dest="clean",
            action="store_true",
            default=False,
            help="Will clean the build",
        )

        parsed = parser.parse_args(args)

        working_dir = os.getcwd()

        if not os.path.exists(os.path.join(working_dir, "config.yaml")):
            msg = "You must run this command inside the exercise directory"
            raise InvalidUserInput(msg)
        fn = os.path.join(working_dir, CF)
        config = load_yaml(fn)
        ws_dir = config["ws_dir"]

        exercise_ws_src = working_dir + "/" + ws_dir + "/src/"

        # Convert all the notebooks listed in the config file to python scripts and
        # move them in the specified package in the exercise ws.
        if "notebooks" in config:
            dtslogger.info("Converting the notebooks into python scripts...")
            for notebook in config["notebooks"]:
                package_dir = exercise_ws_src + notebook["notebook"]["package_name"]
                notebook_name = notebook["notebook"]["name"]

                # bad form
                # notebook_dir = working_dir + f"/notebooks/"
                notebook_dir = os.path.join(working_dir, "notebooks")

                convertNotebook(notebook_dir, notebook_name, package_dir)

        client = check_docker_environment()

        if parsed.staging:
            ros_template_image = AIDO_REGISTRY + "/" + ROS_TEMPLATE_IMAGE
        else:
            ros_template_image = ROS_TEMPLATE_IMAGE

        if parsed.debug:
            cmd = "bash"
        elif parsed.clean:
            cmd = ["catkin", "clean", "--workspace", f"{ws_dir}"]
        else:
            cmd = ["catkin", "build", "--workspace", f"{ws_dir}"]

        container_name = "ros_template_catkin_build"
        remove_if_running(client, container_name)
        ros_template_volumes = {}
        ros_template_volumes[working_dir + f"/{ws_dir}"] = {"bind": f"/code/{ws_dir}", "mode": "rw"}

        ros_template_params = {
            "image": ros_template_image,
            "name": container_name,
            "volumes": ros_template_volumes,
            "command": cmd,
            "stdin_open": True,
            "tty": True,
            "detach": True,
            "remove": True,
            "stream": True,
        }

        pull_if_not_exist(client, ros_template_params["image"])
        ros_template_container = client.containers.run(**ros_template_params)
        attach_cmd = f"docker attach {container_name}"
        start_command_in_subprocess(attach_cmd)

        dtslogger.info("Build complete")


def convertNotebook(filepath, filename, export_path) -> bool:
    import nbformat  # install before?
    from nbconvert.exporters import PythonExporter
    from traitlets.config import Config

    filepath += f"{filename}.ipynb"
    if not os.path.isfile(filepath):
        msg = f"No such file '{filepath}'. Make sure the config.yaml is correct."
        raise Exception(msg)

    nb = nbformat.read(filepath, as_version=4)

    # clean the notebook:
    c = Config()
    c.TagRemovePreprocessor.remove_cell_tags = ("skip",)

    exporter = PythonExporter(config=c)

    # source is a tuple of python source code
    # meta contains metadata
    source, _ = exporter.from_notebook_node(nb)

    try:
        with open(export_path + "/src/" + filename + ".py", "w+") as fh:
            fh.writelines(source)
    except Exception:
        dtslogger.error(traceback.format_exc())
        return False

    return True


def load_yaml(file_name):
    with open(file_name) as f:
        try:
            env = yaml.load(f, Loader=yaml.FullLoader)
        except Exception as e:
            msg = f"Error loading YAML from {file_name}"
            raise Exception(msg) from e
        return env

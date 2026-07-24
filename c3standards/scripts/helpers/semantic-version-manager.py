# Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
# Confidential and Proprietary C3 Materials.
# This material, including without limitation any software, is the confidential trade secret and proprietary
# information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
# strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
# This material may be covered by one or more patents or pending patent applications.

# pylint: disable=broad-exception-raised, broad-exception-caught, too-many-arguments
import argparse
import glob
import json
import os
import sys
import subprocess
from collections import defaultdict

PATH_TO_SCRIPT = "c3standards/scripts/helpers/semantic-version-manager.py"
ROOT_DIR = os.getcwd().replace(PATH_TO_SCRIPT, "")


class C3PkgDecl:
    """
    Class to represent a `Pkg.Decl` instance - constructed from a `c3pkg.json` file.
    """

    def __init__(self, filepath):
        self.name = None  # Store the package name
        self.filepath = filepath  # Store the file path
        self.contents: dict = {}  # Initialize the contents to None
        self.load_json()

    def load_json(self):
        try:
            with open(self.filepath, "r", encoding="utf-8") as file:
                self.contents = json.load(file)  # Load and store the JSON contents
                self.name = self.contents["name"]
        except FileNotFoundError:
            print(f"File not found: {self.filepath}")
        except json.JSONDecodeError as jde:
            print(f"Error decoding JSON in file {self.filepath}: {jde}")
        except Exception as e:
            print(f"An error occurred while reading {self.filepath}: {e}")

    def bump_dependency_versions(self, package_names, updated_version):
        dependencies = self.contents.get("dependencies", {})
        if dependencies:
            for package in package_names:
                if package in dependencies:
                    dependencies[package] = get_major_minor_version(updated_version)

            self.contents: dict = {**self.contents, "dependencies": dependencies}

    def bump_package_version(self, updated_version):
        self.contents: dict = {**self.contents, "version": updated_version}

    def write_updated_file(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as file:
                json.dump(self.contents, file, indent=2)
                file.write("\n")
        except Exception as e:
            sys.exit(f"An error occurred while writing to the file: {e}")


def validate_version(version):
    """
    Given a semantic version validates if it corresponds to a valid semantic version.
    Users must specific a `major`, `major.minor` or `major.minor.patch`. Example: `16`, `16.1`, or `16.1.3`.
    """
    version_components = version.split(".")
    error_message = (
        f"\nInvalid semantic version {version}! " "Please specify a `major.minor`. Example: `8.8`, or `16.1`.\n"
    )

    # Raise a validation error if the version doesn't have 2 components (`Major.Minor`).
    if len(version_components) != 2:
        sys.exit(error_message)

    # Raise a validation error all components are not non-negative integers.
    for version_component in version_components:
        if not version_component.isnumeric() or int(version_component) < 0:
            sys.exit(error_message)


def validate_dependency_version(version, raise_error=False):
    """
    Given a semantic version validates that the dependency version omits the `patch` component, i.e., only sets
    `major.minor` or `major`.
    """
    version_components = version.split(".")
    error_message = (
        f"\nInvalid semantic version {version} for dependency! "
        "Please specify only a `major.minor` convention. Example: `16.1`.\n"
    )

    # Raise a validation error if the version doesn't have between 1-2 components.
    if not len(version_components) == 2:
        if raise_error:
            raise sys.exit(error_message)
        return False

    # Raise a validation error all components are not non-negative integers.
    for version_component in version_components:
        if not version_component.isnumeric() or int(version_component) < 0:
            if raise_error:
                raise sys.exit(error_message)
            return False

    return True


def sh(command, print_output=False) -> str:
    """
    Execute a shell command

    Inputs:
    - command: the command to run in the shell
    - print_output: boolean to indicate whether to print the output of the command

    Outputs:
    - the response string of the command
    """
    if not isinstance(command, list):
        command = command.split(" ")

    response = subprocess.run(command, capture_output=True, check=False)

    if response.returncode == 0:
        response_str = response.stdout.decode("utf-8")
    else:
        response_str = response.stderr.decode("utf-8")

    if print_output:
        print(f"{response_str}")

    return response_str


def get_full_version(version):
    """
    Given a semantic version with just the `major` or `major.minor` components, returns the full semantic version
    including the path version. For example:
    - `16` -> `16.0.0`
    - `16.1` -> `16.1.0`
    - `16.1.3` -> `16.1.3`

    Inputs:
    - version: the trimmed semantic to get the full version for

    Outputs:
    - the full semantic version
    """
    version_components = version.split(".")
    version_components = version_components + (["0"] * (3 - len(version_components)))
    return ".".join(version_components)


def get_major_minor_version(version):
    """
    Given a semantic version, returns the semantic version with the `Major.Minor` convention.
    For example:
    - `16` -> `16.0`
    - `16.1` -> `16.1`
    - `16.1.3` -> `16.1`

    Inputs:
    - version: the trimmed semantic to get the full version for

    Outputs:
    - the `Major.Minor` formatted semantic version
    """
    version_components = version.split(".")

    if len(version_components) > 2:
        final_version = ".".join(version_components[:2])
    else:
        final_version = ".".join(version_components + (["0"] * (2 - len(version_components))))
    return final_version


def find_c3pkg_json_files(directory, subdirectory):
    """
    Returns a list of all `c3pkg.json` at the `directory/subdirectory` path.

    Inputs:
    - directory: the path to the root of the repository in which semantic versions need to be updated
    - subdirectory: the packages path in which to update semantic versions

    Outputs:
    - the list of `c3pkg.json` files at `directory/subdirectory`
    """
    # Construct the path to the subdirectory
    subdirectory_path = os.path.join(directory, subdirectory) if subdirectory else directory
    search_pattern = os.path.join(subdirectory_path, "**/*c3pkg.json")
    return subdirectory_path, glob.glob(search_pattern)


def pretty_print_versioning_violations_and_exit(versioning_violations, path):
    """
    Throws a pretty-printed message outlining versioning validation errors.

    Inputs:
    - versioning_violations: map of versioning validations
    - path: packages path to use when constructing error message
    """
    error_message = []
    for package, pkg_versioning_violations in versioning_violations.items():
        error_message.append(f"\n- {path}/{package}/{package}.c3pkg.json")
        for violation in pkg_versioning_violations:
            error_message.append(f"  - {violation}")
    error_message = "\n".join(error_message)

    sys.exit(f"\nPlease address the following semantic version validation errors:\n {error_message} \n")


def validate_c3pkg_decls(c3pkg_decls):
    """
    Runs validation checks on the C3 Pkg.Decl files in the repository and returns the current semantic versions
    for packages in the repository. The following validation rules are run:
    - All packages must have a defined version
    - There must be only one unique semantic version across packages in the same repository
    - All package declarations must have a `Major.Minor` format

    Inputs:
    - c3pkg_decls: the list of C3 Pkg.Decls to validate

    Outputs:
    - the current semantic version of packages in the repository
    """
    pkgs_by_version = defaultdict(list)
    versioning_violations = defaultdict(list)
    has_errors = False

    # First pass on `c3pkg.json` files to determine validity of defined versions.
    for c3pkg_decl in c3pkg_decls["c3pkg_decls"]:
        name = c3pkg_decl.contents["name"]
        version = c3pkg_decl.contents.get("version", None)

        if version:
            full_version = get_full_version(version)
            pkgs_by_version[full_version].append(name)
        else:
            versioning_violations[name].append(
                f"{name} is missing a semantic version. Please add a semantic version in the `version` field."
            )

    # Throw an error if there is more than one unique package version defined at the same packages path.
    if len(pkgs_by_version) > 1:
        error_message = (
            "\n"
            "There can't be more than one version for the packages in the same repository.\n"
            "Found versions: \n"
            f"{json.dumps(pkgs_by_version, indent=4)}"
        )
        sys.exit(error_message)

    if len(versioning_violations) != 0:
        pretty_print_versioning_violations_and_exit(versioning_violations, c3pkg_decls["path"])

    # The current version at the packages path is the unique version set on all `c3pkg.json` files.
    current_version = next(iter(pkgs_by_version), None)
    major_minor_version = get_major_minor_version(current_version)

    for c3pkg_decl in c3pkg_decls["c3pkg_decls"]:
        name = c3pkg_decl.name
        dependencies = c3pkg_decl.contents["dependencies"] if "dependencies" in c3pkg_decl.contents else {}
        for dependency, dependency_version in dependencies.items():
            if dependency_version.strip() == "*":
                versioning_violations[name].append(f"{dependency} must have a specific semantic version range")

            if dependency in c3pkg_decls["package_names"] and dependency_version != major_minor_version:
                versioning_violations[name].append(f"{dependency} must have latest version {current_version}")

            if not validate_dependency_version(dependency_version):
                versioning_violations[name].append(f"Dependency {dependency} must have a valid `major.minor` version.")

    if len(versioning_violations) != 0:
        has_errors = True
        pretty_print_versioning_violations_and_exit(versioning_violations, c3pkg_decls["path"])

    return current_version, has_errors


def get_c3pkg_decls(path):
    """
    Given the path from the root of the repository and the packages path, returns a list of `C3PkgDecl` objects
    for `.c3pkg.json` files at that path.

    Inputs:
    - path: the packages path in which to update semantic versions

    Outputs:
    - an object with fields:
        - c3pkg_decls - `C3PkgDecl`instances
        - package_names - a set of package names at the packages path
        - subdirectory_path - the absolute subdirectory path
        - path - the packages path
    """
    subdirectory_path, filepaths = find_c3pkg_json_files(ROOT_DIR, path)

    package_names = set()
    c3pkg_decls = []
    for filepath in filepaths:
        c3pkg_decl = C3PkgDecl(filepath=filepath)
        c3pkg_decls.append(c3pkg_decl)
        package_names.add(c3pkg_decl.name)

    return {
        "c3pkg_decls": c3pkg_decls,
        "package_names": package_names,
        "subdirectory_path": subdirectory_path,
        "path": path,
    }


def get_updated_semantic_version(current_version, component):
    """
    Accepts the current semantic version and the component to update. Returns the updated semantic version.

    Inputs:
    - current_version: the current version to update.
    - component: the semantic version component to update - must be one of major, minor or patch

    Outputs:
    - the updated semantic version
    """
    version_components = get_full_version(current_version).split(".")

    updated_version_components = []
    if component == "major":
        updated_version_components = [str(int(version_components[0]) + 1), "0", "0"]
    elif component == "minor":
        updated_version_components = [version_components[0], str(int(version_components[1]) + 1), "0"]
    elif component == "patch":
        updated_version_components = [version_components[0], version_components[1], str(int(version_components[2]) + 1)]

    return ".".join(updated_version_components)


def update_pkg_path_versions(c3pkg_decls, version):
    """
    Function to iterate through all package declarations and
    modify the semantic version.

    Inputs:
    - c3pkg_decls: the list of C3 Pkg.Decls on which to update semantic version
    - version: the semantic version to update to

    Outputs:
    - the updated c3pkg.json files
    """
    updated_c3pkg_decls = []

    for c3pkg_decl in c3pkg_decls["c3pkg_decls"]:
        c3pkg_decl.bump_package_version(version)
        c3pkg_decl.bump_dependency_versions(c3pkg_decls["package_names"], version)
        c3pkg_decl.write_updated_file()
        updated_c3pkg_decls.append(c3pkg_decl)

    return updated_c3pkg_decls


def bump_semantic_versions(c3pkg_decls, current_version, component):
    """
    Accepts the semantic version update component, root of repository and the packages path, and updates and writes
    back the updated semantic version to all `c3pkg.json` files.

    Inputs:
    - c3pkg_decls: the list of C3 Pkg.Decls on which to update semantic version
    - current_version: the current version of packages in the repository
    - component: the semantic version component to update - must be one of major, minor or patch
    """
    # Get the updated semantic version
    updated_version = get_updated_semantic_version(current_version, component)

    # Get the updated semantic version
    update_pkg_path_versions(c3pkg_decls, updated_version)

    print(f"Successfully updated semantic version from {current_version} to {updated_version}")


def update_external_dependency_version(c3pkg_decls, args):
    """
    Accepts the name of dependency package and target semantic version, and updates and writes
    back the updated semantic version to all relevant `c3pkg.json` files.

    Inputs:
    - c3pkg_decls: the list of C3 Pkg.Decls on which to update semantic version
    - args: the CLI arguments passed into the Python script
    """
    # Validate specified semantic version.
    validate_dependency_version(args.version, raise_error=True)

    if args.package in c3pkg_decls["package_names"]:
        sys.exit(
            (
                f"\n[Invalid Request] {args.package} belongs to this repository and cannot be updated independently!"
                "\n\n"
                "Run `make version-bump -h` or `make version-update -h` to see how to update the semantic version of"
                "all packages in the repository.\n"
            )
        )

    # Get the updated semantic version
    updated_c3pkg_decls = []
    for c3pkg_decl in c3pkg_decls["c3pkg_decls"]:
        c3pkg_decl.bump_dependency_versions([args.package], args.version)
        c3pkg_decl.write_updated_file()
        updated_c3pkg_decls.append(c3pkg_decl)

    print(f"Successfully updated version for {args.package} to {args.version}")

    return updated_c3pkg_decls


def update_semantic_versions(c3pkg_decls, args):
    """
    Sets a semantic version for all the packages on the defined path.

    Inputs:
    - c3pkg_decls: the list of C3 Pkg.Decls on which to update semantic version
    - version: the semantic version to update to
    - path: the source folder of for the packages to modify

    Outputs:
    - the updated c3pkg.json files
    """
    # validate the semantic version
    validate_version(args.version)

    # Get the full semantic version
    full_version = get_full_version(args.version)

    # Update all package declarations with the new semantic version
    updated_c3pkg_decls = update_pkg_path_versions(c3pkg_decls, full_version)

    print(f"Successfully updated semantic versions at packages path '{args.path}' to {full_version}")

    return updated_c3pkg_decls


def get_packages_at_path(path):
    """
    Accepts the name of dependency package and target semantic version, and returns the list of `.c3pkg.json` files
    at that path.

    Inputs:
    - path: the packages path from which to get `.c3pkg.json` files.

    Outputs:
    - c3pkg_decls: the packages path at which to validate `.c3pkg.json` files.
    """
    # Get the list of .c3pkg.json files in the sub-directory
    c3pkg_decls = get_c3pkg_decls(path)

    if len(c3pkg_decls["package_names"]) == 0:
        sys.exit(
            (
                f"\nNo packages found at {c3pkg_decls['subdirectory_path']}! "
                "Please provide a valid path relative to the root of your repository.\n"
            )
        )

    return c3pkg_decls


def get_validated_packages(path):
    """
    Accepts the name of dependency package and target semantic version, and updates and writes
    back the updated semantic version to all relevant `c3pkg.json` files.

    Inputs:
    - path: the packages path at which to validate `.c3pkg.json` files.

    Outputs:
    - c3pkg_decls: the packages path at which to validate `.c3pkg.json` files.
    - current_version: the packages path at which to validate `.c3pkg.json` files.
    """
    # Get the list of .c3pkg.json files in the sub-directory
    c3pkg_decls = get_packages_at_path(path)

    # Validate semantic versions match in the .c3pkg.json
    current_version, has_errors = validate_c3pkg_decls(c3pkg_decls)

    if not has_errors:
        print("Validation completed successfully! No errors found!")

    return c3pkg_decls, current_version


def run_command_pre_validation(args):
    """
    Runs the version command before validating the packages.

    Inputs:
    - args: the arguments passed into the Python file
    """
    # Get the list of .c3pkg.json files in the sub-directory
    c3pkg_decls = get_packages_at_path(args.path)

    # Run the `version-update` function.
    updated_c3pkg_decls = args.func(c3pkg_decls=c3pkg_decls, args=args)
    c3pkg_decls["c3pkg_decls"] = updated_c3pkg_decls

    # Validate semantic versions match in the .c3pkg.json
    validate_c3pkg_decls(c3pkg_decls)


def run_command(parser, args):
    """
    Runs the semantic version manager command. Includes some DRY logic to re-use information across version manager
    commands.

    Inputs:
    - parser: the argument parser instance
    - args: the arguments passed into the Python file
    """
    # Call the appropriate function based on the command
    if hasattr(args, "func"):
        # If setting a specific version, set versions and then validate to ensure the package is only throwing an
        # error on external package dependency version errors.
        if args.command in ("version-update", "version-dependency"):
            run_command_pre_validation(args)
            return

        # Validate semantic versions match in the .c3pkg.json
        c3pkg_decls, current_version = get_validated_packages(args.path)

        # Call the function with additional parameters
        if args.command == "version-bump":
            args.func(c3pkg_decls, current_version, args.component)
        return

    parser.print_help()
    return


def validate_parser_inputs(subparser_map, args):
    """
    Validates parser inputs. This is a workaround to let the user run `make version-update` or `make version-bump`
    to see the usage prompt. The Makefile defaults the parameters to an empty string to bypass the validation checks.
    If any of the required args is empty, we show the parser's help message. The path is not part of this check
    as packages can technically be at the root of the repository.

    Inputs:
    - subparser_map: map from command to the subparser for that command
    - args: the arguments passed into the Python file
    """
    if args.command == "version-bump":
        if len(args.component) == 0:
            subparser_map[args.command].print_help()
            return False
    elif args.command == "version-dependency":
        if len(args.package) == 0 or len(args.version) == 0:
            subparser_map[args.command].print_help()
            return False
    elif args.command == "version-update":
        if len(args.version) == 0:
            subparser_map[args.command].print_help()
            return False
    return True


def validate_cwd():
    """
    The script needs to be run from the root of the repository to discover the packages as expected.
    Checks if the script can be found from the root of the repository and throws an error if not.
    """
    if not os.path.exists(os.path.join(ROOT_DIR, PATH_TO_SCRIPT)):
        sys.exit("\nInvalid directory! Please run this script from the root directory of your repository.\n")


def precommit_version_validate(files):
    """
    Validates packages files in the precommit hook. The package paths are inferred from the files `.c3pkg.json`
    files that are changed in the commit.
    """
    # Get the list of changed files in the commit.
    paths = set()

    for file in files:
        # Do nothing for non-c3pkg.json files.
        if not file.endswith("c3pkg.json"):
            continue

        # The paths are inferred as such:
        # - All paths are assumed to be `<root_dir>/<packages_path>/<package_name>/<package_name>.c3pkg.json`
        # - Remove root dir to get `<packages_path>/<package_name>/<package_name>.c3pkg.json`
        # - Split by '/' and re-join by removing last two elements corresponding to
        #   `<package_name>/<package_name>.c3pkg.json` to get `<packages_path>`
        relative_path_components = file.replace(ROOT_DIR, "").split("/")
        paths.add("/".join(relative_path_components[:-2]))

    # Validate all paths for files changed in the pre-commit hook.
    for path in paths:
        get_validated_packages(path)


def main():
    # Validate current working directory.
    validate_cwd()

    # Create an ArgumentParser object
    parser = argparse.ArgumentParser(prog="make", description="Manage package versions.")

    subparsers = parser.add_subparsers(dest="command")

    # Define the 'version-bump' subcommand.
    bump_parser = subparsers.add_parser(
        "version-bump",
        help="Bump repository packages' semantic version. Use `version-update` to set a specific version.",
    )
    bump_parser.add_argument(
        "component",
        # Allow empty choice to be called from the Makefile to pipe the request over the parser and
        # print the command's usage.
        choices=["major", "minor", "patch", ""],
        help="Component of the version to bump (major, minor, patch).",
    )
    bump_parser.add_argument(
        "path",
        help=(
            "Packages path where the version should be bumped. "
            "If not specified, packages are assumed to be located at the root of the repository."
        ),
    )
    bump_parser.set_defaults(func=bump_semantic_versions)

    # Define the 'version-dependency' subcommand
    update_external_dependency_parser = subparsers.add_parser(
        "version-dependency",
        help="Update the version of an external dependency across all packages at the specified packages path.",
    )
    update_external_dependency_parser.add_argument("package", help="Dependency package to update.")
    update_external_dependency_parser.add_argument("version", help="New version to set for the package.")
    update_external_dependency_parser.add_argument(
        "path", help="Subdirectory path where the version should be updated."
    )
    update_external_dependency_parser.set_defaults(func=update_external_dependency_version)

    # Define the `version-update` subcommand
    update_parser = subparsers.add_parser(
        "version-update", help="Set a defined semantic version across all packages in your repository."
    )
    update_parser.add_argument("version", help="New version to set for the packages at path.")
    update_parser.add_argument("path", help="Packages path where the version should be updated.")
    update_parser.set_defaults(func=update_semantic_versions)

    # Define the 'version-validate' subcommand.
    validation_parser = subparsers.add_parser("version-validate", help="Validate semantic versions in your repository.")
    validation_parser.add_argument("path", help="Subdirectory path where the versions should be validated.")
    validation_parser.set_defaults(func=lambda args: get_validated_packages(args.path))

    # Define the 'precommit-version-validate' subcommand. Defined separately since packages path is inferred from
    # changed files and path is not a required parameter.
    precommit_validation_parser = subparsers.add_parser(
        "precommit-version-validate", help="Validate semantic version of all packages in your repository."
    )
    precommit_validation_parser.add_argument(
        "files", nargs="+", help="Subdirectory path where the version should be updated."
    )
    precommit_validation_parser.set_defaults(func=lambda args: precommit_version_validate(args.files))

    # Parse the arguments
    args = parser.parse_args()

    # If the user only wants to validate packages, return without any further subparser validations.
    if args.command in ["version-validate", "precommit-version-validate"]:
        args.func(args)
        return

    subparser_map = {
        "version-bump": bump_parser,
        "version-dependency": update_external_dependency_parser,
        "version-update": update_parser,
    }

    if validate_parser_inputs(subparser_map, args):
        run_command(parser, args)


if __name__ == "__main__":
    main()

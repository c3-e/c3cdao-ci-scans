# Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
# Confidential and Proprietary C3 Materials.
# This material, including without limitation any software, is the confidential trade secret and proprietary
# information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
# strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
# This material may be covered by one or more patents or pending patent applications.

# pylint: disable=line-too-long, consider-using-f-string, broad-exception-raised, broad-exception-caught, too-many-arguments
import os
import shutil
import sys
import json
import subprocess


FILES_TO_DELETE = [
    ".vale/",
    "scripts/c3standards-upgrader/",
    "scripts/hooks/",
    "scripts/semantic-version-manager/",
    "setup/",
    ".eslintrc",
    ".prettierrc",
    ".stylelintrc",
    "LICENSE",
    "Makefile",
    "OLD_LICENSE",
]


def getVersionMatrixValue(version, key):
    """
    Function to get the value from a key on the Version Matrix.

    Inputs:
    - version: The version identifier
    - key: The specific field whose value should be returned
    """

    with open("c3standards/scripts/versionMatrix.json", "r", encoding="utf-8") as file:
        try:
            version_matrix = json.load(file)
            base_files = version_matrix["baseFiles"]
            new_files = version_matrix["versionMatrix"][version][key]
            return [*base_files, *new_files]
        except Exception as e:
            print(f"An error ocurred: {e}")
            sys.exit(1)


def move_files(target_dir):
    """
    Function to move a set of files from the cloned repository
    into the one to update/integrate c3standards to

    Inputs:
    - target_dir: The target directory where the files will be deleted
    """

    tmp_dir = os.getcwd()
    files_to_move = getVersionMatrixValue("8.9", "include")

    for file_name in files_to_move:
        src_path = os.path.join(tmp_dir, file_name)
        dest_path = os.path.join(target_dir, file_name)

        dest_dir = os.path.dirname(dest_path)
        os.makedirs(dest_dir, exist_ok=True)

        if os.path.exists(dest_path):
            if os.path.isdir(dest_path):
                shutil.rmtree(dest_path)
            else:
                os.remove(dest_path)

        shutil.move(src_path, dest_path)


def delete_files(target_dir):
    """
    Function to delete a set of no longer required files
    from a target directory (normally at root of the repository)

    Inputs:
    - target_dir: The target directory where the files will be deleted
    """
    for file_name in FILES_TO_DELETE:
        target_path = os.path.join(target_dir, file_name)

        if os.path.exists(target_path):
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            else:
                os.remove(target_path)


def move_vale_styles():
    """
    Function to help move all current styles into
    the c3standards folder
    """

    source_dir = ".vale/styles"
    target_dir = "c3standards/config/vale/styles"
    skip_items = {"C3", "config", "alex", "Microsoft"}

    if not os.path.exists(source_dir):
        print("No Vale folder found at the root of the repository")
        sys.exit(1)

    try:
        for item in os.listdir(source_dir):
            if item in skip_items:
                continue

            src_path = os.path.join(source_dir, item)
            dest_path = os.path.join(target_dir, item)
            shutil.move(src_path, dest_path)
    except Exception as e:
        print(f"An error ocurred: {e}")
        sys.exit(1)


def read_rcfile(filename):
    """
    Returns the contents of the provided file

    Inputs:
    - filename: the name of the file to read contents from

    Outputs:
    - the response from the pull request query
    """

    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as file:
                file_contents = file.read()
            return json.loads(file_contents)
        except Exception as e:
            print(e)
            raise e

    return None


def write_file(filename, content):
    """
    Writes the provided contents to the provided file

    Inputs:
    - filename: the name of the file to write the contents to
    - content: the string contents to write
    """

    with open(filename, "w", encoding="utf-8") as file:
        file.write(content)


def create_standards_rc(sha, branch_name):
    """
    Updated the '.c3standardsrc' file with the latest sha and branch_name

    Inputs:
    - sha: The SHA of the cloned support branch
    - branch_name: The current source branch set at c3standards.sh used to pull in changes
    """

    rcfile_contents = read_rcfile(".c3standardsrc")

    if rcfile_contents is not None:
        rcfile_contents["sha"] = sha
        rcfile_contents["branchName"] = branch_name
    else:
        rcfile_contents = {"sha": sha, "branchName": branch_name}

    write_file(".c3standardsrc", json.dumps(rcfile_contents))


def invoke_https_request(url, headers, body):
    """
    Execute a HTTPS request

    Inputs:
    - url: the request endpoint
    - headers: the request headers
    - body: the request body. If empty, a GET request will be invoked.

    Outputs:
    - the JSON response of the request
    """
    import requests

    if body is None:
        response = requests.get(url=url, headers=headers, timeout=15)
    else:
        response = requests.post(url=url, headers=headers, json=body, timeout=15)
    if response.status_code == 200:
        return response.json()
    raise Exception(f"Request to {url} failed with code of {response.status_code}. {response.content}")


def graphql_request(query):
    """
    Executes the provided GraphQL query

    Inputs:
    - query: the GraphQL query to execute

    Outputs:
    - the response of the GraphQL query
    """
    GITHUB_TOKEN = str(os.environ["GITHUB_TOKEN"])
    headers = {"Authorization": "Bearer " + GITHUB_TOKEN}
    response = invoke_https_request("https://api.github.com/graphql", headers, {"query": query})
    return response


def get_repository_node_id(repo):
    """
    Fetches the repository GraphQL node id

    Inputs:
    - repo: the name of the repo - c3base

    Outputs:
    - the GraphQL node id of the repository
    """
    query = """
    query {{
        repository(owner:"c3-e", name:"{}") {{
            id
        }}
    }}
    """.format(
        repo
    )
    response = graphql_request(query)
    print(response)
    return response["data"]["repository"]["id"]


def close_existing_pull_request(repo, head):
    """
    Finds and closes any open pull request with the given head branch.

    Inputs:
    - repo: the name of the repo
    - head: the head branch name to search for
    """
    query = """
    query {{
        repository(owner:"c3-e", name:"{}") {{
            pullRequests(headRefName:"{}", states:OPEN, first:10) {{
                nodes {{
                    id
                    number
                    url
                }}
            }}
        }}
    }}
    """.format(
        repo, head
    )

    response = graphql_request(query)

    try:
        prs = response["data"]["repository"]["pullRequests"]["nodes"]
    except (KeyError, TypeError):
        return

    for pr in prs:
        print(f"Closing existing PR #{pr['number']}: {pr['url']}")
        mutation = """
        mutation {{
            closePullRequest(input: {{ pullRequestId: "{}" }}) {{
                pullRequest {{ number state }}
            }}
        }}
        """.format(
            pr["id"]
        )
        graphql_request(mutation)


def create_pull_request(repo, title, head, base, body):
    """
    Creates a pull request using the provided pull request parameters

    Inputs:
    - repo: the name of the repo to post the pull request to
    - title: the title of the pull request
    - head: the branch being merged in
    - base: the base branch to merge into
    - body: the body of the pull request

    Outputs:
    - the response from the pull request query
    """
    repo_node_id = get_repository_node_id(repo)

    print("Creating pull request for:")
    print(f"repo: {repo}")
    print(f"repo_node_id: {repo_node_id}")
    print(f"title: {title}")
    print(f"head: {head}")
    print(f"base: {base}")
    print(f"body:\n{body}")

    escaped_body = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')

    mutation = """
    mutation {{
        createPullRequest(input: {{
            repositoryId: "{}",
            baseRefName: "{}",
            title: "{}",
            headRefName: "{}"
            body: "{}"
        }}) {{
            pullRequest {{
                number
                url
                title
            }}
        }}
    }}
    """.format(
        repo_node_id, base, escaped_title, head, escaped_body
    )
    response = graphql_request(mutation)

    try:
        pr = response["data"]["createPullRequest"]["pullRequest"]
        pr_url = pr["url"]
        pr_number = pr["number"]
        pr_title = pr["title"]

        print(f"\n{'=' * 60}")
        print(f"Pull Request created successfully!")
        print(f"  Title:  {pr_title}")
        print(f"  PR:     #{pr_number}")
        print(f"  URL:    {pr_url}")
        print(f"{'=' * 60}\n")

        print(f"::notice title=C3 Standards PR Created::#{pr_number} - {pr_title}: {pr_url}")

        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_file:
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(f"## C3 Standards PR Created\n\n")
                f.write(f"**[#{pr_number} - {pr_title}]({pr_url})**\n\n")
                f.write(f"Please review the PR and adjust as needed.\n")
    except (KeyError, TypeError):
        print(f"Create pull request response:\n{response}")

    return response


def sh(command, print_output=True):
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
        response_str = response.stdout.decode("utf-8").strip()
    else:
        response_str = response.stderr.decode("utf-8").strip()

    if print_output:
        print(f"{response_str}")

    return response_str


def get_jarvis_pr_body(branch_name, diff_file_names):
    """
    Returns the body to post in the pull request description when the user has a different configuration.

    Inputs:
    - branch_name: the source branch to apply patches from

    Outputs:
    - the body of the pull request to be posted
    """
    filtered_names = [name for name in diff_file_names if name.strip()]
    file_names_message = []
    for file in filtered_names:
        file_names_message.append(f"- {file}.js")
    jarvis_files = "\n".join(file_names_message)
    message = [
        f"This PR surfaces the latest `c3standards` Jarvis step updates for `{branch_name}`",
        "",
        "It was automatically generated after detecting differences in your repository's Jarvis steps/configuration. To ensure that no custom code maintained by your team is lost, the auto upgrader has created this PR to assist with integrating the new steps with your existing ones.",
        "",
        "To proceed, please:",
        "",
        "1. Pull this commit into your local branch.",
        "2. Review the updated Jarvis steps located in the `updatedSteps` folder.",
        "3. Adjust the steps as necessary to align with your repository's requirements.",
    ]
    return "\n".join(message)


def create_jarvis_pr(show_output, diff_file_names):
    """
    Creates a PR for integrating the latest Jarvis updates into a repository

    Inputs:
    - show_output: Boolean value. Display the output code on the console
    """
    GITHUB_CONTEXT = os.environ["GITHUB_CONTEXT"]
    github_context = json.loads(GITHUB_CONTEXT)

    branch_name = sh("git branch --show-current", show_output)
    new_branch_name = f"{branch_name}-JarvisPR"

    sh(f"git checkout -b {new_branch_name}", show_output)
    sh("git add .", show_output)
    sh(
        [
            "git",
            "commit",
            "-m",
            f"Attempt to merge the latest `c3standards` Jarvis steps into `{branch_name}`",
            "--no-verify",
            "--no-edit",
        ]
    )
    sh(f"git push --force origin {new_branch_name}", show_output)

    repo = github_context["event"]["repository"]["name"]
    title = "Attempt to merge c3standards Jarvis updates"
    body = get_jarvis_pr_body(branch_name, diff_file_names)

    close_existing_pull_request(repo, new_branch_name)
    create_pull_request(repo, title, new_branch_name, branch_name, body)


def main():
    command = sys.argv[1]
    param_1 = sys.argv[2] if len(sys.argv) > 2 else "null"
    param_2 = sys.argv[3] if len(sys.argv) > 3 else "null"

    if command == "move":
        move_files(param_1)
    elif command == "delete":
        delete_files(param_1)
    elif command == "move_styles":
        move_vale_styles()
    elif command == "create_standards_rc":
        create_standards_rc(param_1, param_2)
    elif command == "get_rc_key":
        rcfile_contents = read_rcfile(".c3standardsrc")
        if rcfile_contents:
            print(rcfile_contents.get(param_1, ""))
    elif command == "update_jarvis":
        create_jarvis_pr(True, sys.argv[2:])
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()

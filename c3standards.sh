#!/bin/bash

C3_STD_INPUT_COMMAND=$1
shift

# Directories
C3_STD_SETUP_DIR="./c3standards/setup/"

# Tools
C3_STD_HELPER_FOLDER="./c3standards/scripts/helpers"
C3_STD_VERSION_MANAGER="$C3_STD_HELPER_FOLDER/semantic-version-manager.py"
C3_STD_LINT_CONVERTER="$C3_STD_HELPER_FOLDER/lint_converter.js"
C3_STD_PKG_CONVERTER="$C3_STD_HELPER_FOLDER/package_converter.js"
C3_STD_LOCAL_STANDARDS_EXECUTOR="$C3_STD_HELPER_FOLDER/c3standards_executor.py"

# Branch
C3_STD_BRANCH="support/v8.10"

# Repositories
REPO_ROOT=$(git rev-parse --show-toplevel 2>&1)
if [[ -n $REPO_ROOT ]]; then
  C3_STD_REPO_NAME=$(basename "$REPO_ROOT")
else
  C3_STD_REPO_NAME="the current repository."
fi
C3_STD_CLONE_SHA=""
C3_STD_REPO_URL=""

# Variables for customization
C3_STD_CREATE_COMMIT=""
C3_STD_CREATE_PACKAGE=""
C3_STD_PACKAGE_NAME=""
C3_STD_PACKAGE_DESCRIPTION=""
C3_STD_PROTOCOL=""
C3_STD_PAT=""
C3_RAISE_JARVIS_WARNING=true

# HELPER FUNCTIONS

# Function to display help information
show_help() {
  echo "C3 Standards Tool - Standardization and tooling for C3 repositories"
  echo ""
  echo "Usage: c3standards <command> [options]"
  echo ""
  echo "Setup Commands:"
  echo "  init                 Initialize C3 standards in your repository"
  echo "                       Downloads and integrates the latest standards"
  echo "  setup                Run the complete setup process for development tools"
  echo "  install              Install required dependencies and tools"
  echo ""
  echo "Update Commands:"
  echo "  update               Update to the latest C3 standards from the repository"
  echo "  update-github        Helper for updating C3 standards via GitHub Actions workflow"
  echo "                       Usage: c3standards update-github <source-branch> <target-branch> <token>"
  echo ""
  echo "Version Management:"
  echo "  version-validate     Validate version format and dependencies"
  echo "  version-update       Update version numbers in project files"
  echo "  version-bump         Bump version (patch, minor, or major)"
  echo "  version-dependency   Manage and update version dependencies"
  echo ""
  echo "Examples:"
  echo "  c3standards init                    # Initialize standards in current repo"
  echo "  c3standards update                  # Update to latest standards"
  echo "  c3standards version-bump patch      # Bump patch version"
  echo ""
  echo "For more information, visit: https://github.com/c3-e/c3standards"
}

# Function to output an error message if an action fails.
function handle_error () {
  echo "Error: $1"
  exit 1
}

# Function to check if the local machine has everything required to run this script.
# If the user doesn't have a specific requirement, it installs it.
function pre_init() {
  function handle_error() {
    echo "$1"
    exit 1
  }

  function check_and_install() {
    local name=$1
    local install_mac=$2
    local install_linux=$3

    if ! command -v "$name" >/dev/null 2>&1; then
      echo "$name not found. Attempting to install..."
      unameOut="$(uname -s)"
      case "${unameOut}" in
          Darwin*)
            eval "$install_mac" || handle_error "Unable to install $name on macOS"
            ;;
          Linux*)
            eval "$install_linux" || handle_error "Unable to install $name on Linux"
            ;;
          *)
            handle_error "Unsupported OS: $unameOut"
            ;;
      esac
    fi
  }

  # Python3
  check_and_install "python3" \
    'which brew >/dev/null 2>&1 || /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; brew install python' \
    'sudo apt-get update && sudo apt-get install -y python3 python3-pip'

  # Ansible
  check_and_install "ansible" \
    "$HOME/Library/Python/3*/bin/pip3 install --user ansible || pip3 install --user ansible" \
    "pip3 install --user ansible"

  # Vale
  check_and_install "vale" \
    'brew install vale' \
    'curl -fsSL https://github.com/errata-ai/vale/releases/latest/download/vale_Linux_64-bit.tar.gz | tar -xz && sudo mv vale /usr/local/bin'

  # gum (for better user interface)
  check_and_install "gum" \
    'brew install gum' \
    'sudo apt update && sudo apt install gum -y'

  # Lodash
  if command -v npm >/dev/null 2>&1; then
    if ! npm list lodash >/dev/null 2>&1; then
      npm install lodash --no-save >/dev/null 2>&1 || handle_error "Failed to install lodash"
    fi
  else
    handle_error "npm not found. Cannot install lodash"
  fi
}

# Function to ask the user if they would like to automatically
# commit the changes after a workflow has been completed.
function commit_prompt() {
  echo
  echo "This function will make several changes to your current working repository."
  echo "Do you want to commit changes automatically?"
  echo
  answer=$(GUM_CHOOSE_CURSOR_FOREGROUND="#8FCE00" \
           gum choose "Yes" "No")

  case $answer in
    Yes)
      C3_STD_CREATE_COMMIT=true
      ;;
    No)
      C3_STD_CREATE_COMMIT=false
      ;;
  esac
}

# Function to prompt the user to select a preferred communication protocol.
function protocol_prompt() {
  echo "This workflow will connect to GitHub to download the latest files for setup or updates."
  echo "Select any of the options shown below."

  C3_STD_PROTOCOL=$(GUM_CHOOSE_CURSOR_FOREGROUND="#8FCE00" \
                    gum choose "SSH" "HTTPS")
}

# Function to generate the output error message for failed Jarvis updates.
function generate_jarvis_message() {
  local steps=$@
  echo -e "\033[1;31mUnable to update the following Jarvis Steps...\033[0m\n"
  for step in $steps;
  do
    echo -e "\033[1;31m- $step\033[0m"
  done
  echo
  echo -e "\033[1;31mPlease update steps manually, reference files located at the '.jarvis/updatedSteps' folder\033[0m\n"
}

# Function to help determine if Jarvis should be updated or sent for review.
function run_jarvis_update() {
  NEW_STEPS=$(find c3standards/jarvis/steps -type f -not -name config.js)
  JARVIS_PATH=.jarvis/steps/
  JARVIS_UPDATED_PATH=.jarvis/updatedSteps/
  DIFF_FILE_PATHS=()
  DIFF_FILE_NAMES=()

  IS_LOCAL=$1

  npx prettier --write .jarvis/ >/dev/null
  npx prettier --write c3standards/jarvis/ >/dev/null

  for step in $NEW_STEPS;
  do
    file_name=$(basename $step)
    if ! git diff --no-index --quiet "$JARVIS_PATH$file_name" $step >/dev/null 2>&1; then
      DIFF_FILE_PATHS+=("$step")
      DIFF_FILE_NAMES+=("$file_name")
    fi
  done

  if [ ${#DIFF_FILE_PATHS[@]} -gt 0 ]; then
    mkdir -p $JARVIS_UPDATED_PATH
    for path in ${DIFF_FILE_PATHS[@]};
    do
      cp $path $JARVIS_UPDATED_PATH
    done
    $IS_LOCAL && {
      generate_jarvis_message ${DIFF_FILE_NAMES[@]}
    } || {
      python3 $C3_STD_LOCAL_STANDARDS_EXECUTOR update_jarvis ${DIFF_FILE_NAMES[@]}
    }
  fi
}

# Function to validate if 8.9+ standards integration is already on the current
# working repository.
function check_for_init() {
 if grep -q "branchName" .c3standardsrc; then
  echo "Upgraded standards already integrated into $C3_STD_REPO_NAME"
  echo "To fetch the latest changes, run './c3standards.sh update' instead."
  exit 0
 fi
}

# Function to uncomment the auto upgrader after init/update process.
function uncomment_upgrader() {
  if [ $(uname) == "Darwin" ]; then
    sed -i '' -E '6,10s/^([[:space:]]*)#[[:space:]]?/\1/' .github/workflows/c3standards-upgrader.yml
  else
    sed -i -E '6,10s/^([[:space:]]*)#[[:space:]]?/\1/' .github/workflows/c3standards-upgrader.yml
  fi
}

# Function to systematically update the gitignore file to align with the latest
# contents from the one on the source branch
function update_git_ignore() {
  local tmp_dir="$1"

  # Append only the source entries that aren't already present locally.
  # grep -Fxv matches whole lines literally and -- unlike `comm` -- does not
  # require either file to be sorted, so it stays idempotent and won't
  # re-append the full ignore block on every automated update.
  grep -Fxv -f .gitignore "$tmp_dir/.gitignore" >> .gitignore || true

  # Heal any duplication left behind by the previous `comm`-based logic:
  # drop repeated pattern lines (keeping the first occurrence) while
  # preserving blank lines and comments so the file structure is untouched.
  local deduped
  deduped=$(awk '!/^$/ && !/^[[:space:]]*#/ { if (seen[$0]++) next } { print }' .gitignore)
  printf '%s\n' "$deduped" > .gitignore
}

# MAIN COMMANDS
case $C3_STD_INPUT_COMMAND in
  # Version Management
  version-*)
      if [ ! -f $C3_STD_VERSION_MANAGER ]; then
        echo "Python executor not found."
        echo "Please install the latest c3standards tools by running 'c3standards init'"
        exit 0
      fi

      case $C3_STD_INPUT_COMMAND in
        version-validate)
          echo "Running Version Validate..."
          python3 $C3_STD_VERSION_MANAGER version-validate $@
          ;;
        version-update)
          echo "Running Version Update..."
          python3 $C3_STD_VERSION_MANAGER version-update $@
          ;;
        version-bump)
          echo "Running Version Bump..."
          python3 $C3_STD_VERSION_MANAGER version-bump $@
          ;;
        version-dependency)
          echo "Running Version Dependency..."
          python3 $C3_STD_VERSION_MANAGER version-dependency $@
          ;;
      esac
      exit 0
    ;;
  # Setup and Install tools
  setup|install)
    if [ ! -d $C3_STD_SETUP_DIR ]; then
      echo "Setup folder not found."
      echo "Please install the latest c3standards tools by running 'c3standards init'"
      exit 0
    fi

    cd $C3_STD_SETUP_DIR
    case $C3_STD_INPUT_COMMAND in
      install)
        make install
        exit 0
        ;;
      setup)
        make setup
        exit 0
        ;;
    esac
    ;;
  # Integration process from versions 8.8 and lower to 8.9
  init)

    check_for_init

    # Run the pre-init step
    pre_init

    # Temporary directory
    C3_STD_CURRENT_DIR=$(pwd)
    C3_STD_TMP_DIR=$(mktemp -d)
    C3_STD_STANDARDS_EXECUTOR="$C3_STD_TMP_DIR/$C3_STD_LOCAL_STANDARDS_EXECUTOR"

    # Set SSH or HTTPs prompt.
    protocol_prompt

    # Automatic commit prompt
    commit_prompt

    echo
    echo "[INTEGRATING NEW FILES] ..."
    cd $C3_STD_TMP_DIR

    # Clone the c3standards repo based with user preffered protocol
    C3_STD_REPO_URL=$(
      [[ "$C3_STD_PROTOCOL" == "HTTPS" ]] &&
        echo "https://github.com/c3-e/c3standards.git" ||
        echo "git@github.com:c3-e/c3standards.git"
    )

    error=$(
      git clone --depth=1 --branch="$C3_STD_BRANCH" "$C3_STD_REPO_URL" . >/dev/null 2>&1
    ) || handle_error "Unable to clone repo into temp directory... $error"

    C3_STD_CLONE_SHA=$(git rev-parse HEAD)

    echo
    echo "[MOVING FILES] ..."
    python3 "$C3_STD_STANDARDS_EXECUTOR" move "$C3_STD_CURRENT_DIR"
    cd "$C3_STD_CURRENT_DIR"

    if [[ ! -d '/vale' ]]; then
      # Copy base configuration and move it to root
      cp c3standards/config/.vale.base.ini .vale.ini
    else
      # Move Vale styles into new folder
      python3 $C3_STD_LOCAL_STANDARDS_EXECUTOR move_styles
    fi

    # Update the current 'package.json'
    node "$C3_STD_PKG_CONVERTER" "$C3_STD_TMP_DIR"
    echo "" >> package.json

    update_git_ignore $C3_STD_TMP_DIR

    echo
    echo "[INSTALLING DEPENDENCIES] ..."
    error=$(
      npm install 2>&1
    ) || handle_error "Unable to install package dependencies... ${error}"

    echo
    echo "[UPDATING LINTER CONFIGURATIONS] ..."
    node "$C3_STD_LINT_CONVERTER"

    echo
    echo "[REMOVING OUTDATED FILES] ..."
    python3 $C3_STD_LOCAL_STANDARDS_EXECUTOR delete "$C3_STD_CURRENT_DIR"

    uncomment_upgrader

    rm -rf "$C3_STD_TMP_DIR"

    # Create or update the .c3standardsrc file
    python3 $C3_STD_LOCAL_STANDARDS_EXECUTOR create_standards_rc $C3_STD_CLONE_SHA $C3_STD_BRANCH
    echo "" >> .c3standardsrc

    git restore package-lock.json
    git add .
    pre-commit run >/dev/null
    git add .

    $C3_STD_CREATE_COMMIT && git commit -m "[AUTOMATED CHORE] Integrated 8.9 C3 Standards into ${C3_STD_REPO_NAME}" --no-verify >/dev/null 2>&1

    echo
    echo "[UPDATING JARVIS STEPS] ..."
    run_jarvis_update true

    echo "Integrated C3 Standards into ${C3_STD_REPO_NAME}"
    exit 0
    ;;
  # Update current c3standards to latest master
  update)

    # Run the pre-init step
    pre_init

    # Temporary directory
    C3_STD_CURRENT_DIR=$(pwd)
    C3_STD_TMP_DIR=$(mktemp -d)
    C3_STD_STANDARDS_EXECUTOR="$C3_STD_TMP_DIR/$C3_STD_LOCAL_STANDARDS_EXECUTOR"

    # Set SSH or HTTPs prompt.
    protocol_prompt

    echo
    echo "[UPDATING REPOSITORY] ..."
    cd $C3_STD_TMP_DIR

    # Clone the c3standards repo based with user preffered protocol
    C3_STD_REPO_URL=$(
      [[ "$C3_STD_PROTOCOL" == "HTTPS" ]] &&
        echo "https://github.com/c3-e/c3standards.git" ||
        echo "git@github.com:c3-e/c3standards.git"
    )

    error=$(
      git clone --depth=1 --branch="$C3_STD_BRANCH" "$C3_STD_REPO_URL" . >/dev/null 2>&1
    ) || handle_error $error

    C3_STD_CLONE_SHA=$(git rev-parse HEAD)

    echo
    echo "[MOVING FILES] ..."
    python3 "$C3_STD_STANDARDS_EXECUTOR" move "$C3_STD_CURRENT_DIR"

    cd "$C3_STD_CURRENT_DIR"
    # Update the current 'package.json'
    node "$C3_STD_PKG_CONVERTER" "$C3_STD_TMP_DIR"
    echo "" >> package.json

    update_git_ignore $C3_STD_TMP_DIR

    # Install package dependencies
    error=$(
      npm install 2>&1
    ) || handle_error "Unable to install package dependencies... ${error}"

    rm -rf "$C3_STD_TMP_DIR"

    uncomment_upgrader

    # Update the .c3standardsrc file
    python3 $C3_STD_LOCAL_STANDARDS_EXECUTOR create_standards_rc $C3_STD_CLONE_SHA $C3_STD_BRANCH
    echo "" >> .c3standardsrc

    git restore package-lock.json
    git add .
    pre-commit run >/dev/null
    git add .
    git commit -m "[AUTOMATED CHORE] Pulled the latest update from C3 Standards into ${C3_STD_REPO_NAME}" --no-verify > /dev/null

    run_jarvis_update true

    echo "Pulled the latest updates from c3Standards into ${C3_STD_REPO_NAME}!"
    exit 0
    ;;
  # Update current c3standards with Github Actions
  update-github)

    GITHUB_SOURCE_BRANCH=$1
    GITHUB_TARGET_BRANCH=$2
    GITHUB_TOKEN=$3

    npm install lodash --no-save

    # Temporary directory
    C3_STD_CURRENT_DIR=$(pwd)
    C3_STD_TMP_DIR=$(mktemp -d)
    C3_STD_STANDARDS_EXECUTOR="$C3_STD_TMP_DIR/$C3_STD_LOCAL_STANDARDS_EXECUTOR"

    # Get protocol configuration
    C3_STD_PROTOCOL=$(python3 $C3_STD_LOCAL_STANDARDS_EXECUTOR get_rc_key protocol)

    echo
    echo "[UPDATING REPOSITORY] ..."
    cd $C3_STD_TMP_DIR

    git clone --depth=1 --branch="$GITHUB_SOURCE_BRANCH" "https://x-access-token:$GITHUB_TOKEN@github.com/c3-e/c3standards.git" .

    C3_STD_CLONE_SHA=$(git rev-parse HEAD)

    echo
    echo "[MOVING FILES] ..."
    python3 "$C3_STD_STANDARDS_EXECUTOR" move "$C3_STD_CURRENT_DIR"

    cd "$C3_STD_CURRENT_DIR"
    # Update the current 'package.json'
    node "$C3_STD_PKG_CONVERTER" "$C3_STD_TMP_DIR"
    echo "" >> package.json

    update_git_ignore $C3_STD_TMP_DIR

    rm -rf "$C3_STD_TMP_DIR"

    uncomment_upgrader

    # Update the .c3standardsrc file
    python3 $C3_STD_LOCAL_STANDARDS_EXECUTOR create_standards_rc $C3_STD_CLONE_SHA $C3_STD_BRANCH

    git add .
    git commit -m "[AUTOMATED CHORE] Pulled the latest update from \`c3standards\` into \`${C3_STD_REPO_NAME}\`" --no-verify > /dev/null
    git push origin $GITHUB_TARGET_BRANCH

    run_jarvis_update false

    echo "Pulled the latest updates from c3standards into ${GITHUB_TARGET_BRANCH}!"
    exit 0
    ;;

  help|--help|-h)
    show_help
    exit 0
    ;;

  *)
    echo "Unknown command: $C3_STD_INPUT_COMMAND"
    echo ""
    show_help
    exit 1
    ;;
esac

exit 0

.PHONY: all workstation pyenv cleanup setup setup_internal install

# Define default PATH once for all targets that need it. This doesn't set PATH for the shell, only for the Makefile.
# ansible commands are installed at this path.
export PATH := $(HOME)/.local/bin:$(PATH)
export NVM_DIR := $(HOME)/.nvm

# Prefix for any messages delivered by c3standards through the Makefile.
C3_STANDARDS_PREFIX := \033[0;32mc3standards\033[0m:

# Define default target that runs all steps for non workstations.
all: cleanup setup install

# Define the `githubci` target that installs ansible on the GitHub Workflow and runs the setup playbook.
githubci:
	python3 -m pip install --user ansible
	@$(MAKE) setup_internal

# Define the `work` target that installs ansible on the workstation and runs the setup playbook.
workstation:
# GCP workstations do not allow installation of python packages globally in system directories. See https://peps.python.org/pep-0668/. \
	Install pyenv to switch between local installations and default GCP Python installation. \
	We could alternatively install ansible with `sudo apt install ansible`, but any system directories \
	are ephemeral, so users would need to run `make setup` every time their workstation was hibernated.
	@$(MAKE) pyenv
	@if ! command -v ansible-playbook; then \
		echo "${C3_STANDARDS_PREFIX} Installing ansible for local use."; \
		python3 -m pip install --user ansible; \
	fi
	@$(MAKE) setup_internal

# These strings need to be inserted into users' .bashrc and .profile to ensure pyenv is accessible anywhere across sessions.
PYENV_BEGIN_MARKER := \# BEGIN C3STANDARDS MANAGED BLOCK for pyenv
PYENV_LINES := export PYENV_ROOT=\"\$$HOME/.pyenv\"\ncommand -v pyenv > /dev/null || export PATH="\$$PYENV_ROOT/bin:\$$PATH"\neval \"\$$(pyenv init -)\"
PYENV_END_MARKER := \# END C3STANDARDS MANAGED BLOCK for pyenv

# Python version to use with pyenv. Can be changed with `make workstation PYENV_PYTHON_VERSION=3.10`
PYENV_PYTHON_VERSION ?= 3.12
PYENV_DEPS := zlib1g zlib1g-dev libffi-dev libssl-dev libbz2-dev libsqlite3-dev

# Define the `pyenv` target that installs pyenv for workstations, adds it to PATH, and sets the local Python version to 3.9.
pyenv:
# If pyenv isn't installed, install it.
	@if [ ! -d $(HOME)/.pyenv ]; then \
		echo "${C3_STANDARDS_PREFIX} Installing pyenv."; \
		curl -s https://pyenv.run | bash; \
	fi

# Ensure the correct .bashrc commands have been added. If not, add them.
	@if ! grep -Fxq "${PYENV_BEGIN_MARKER}" $(HOME)/.bashrc; then \
		echo "\n${PYENV_BEGIN_MARKER}\n${PYENV_LINES}\n${PYENV_END_MARKER}" >> $(HOME)/.bashrc; \
		echo "\n${PYENV_BEGIN_MARKER}\n${PYENV_LINES}\n${PYENV_END_MARKER}" >> $(HOME)/.profile; \
		echo "${C3_STANDARDS_PREFIX} pyenv was just installed. Please restart your terminal to ensure pyenv works correctly, then run \033[0;33mmake workstation\033[0m again."; \
		exit 1; \
	fi

# These dependencies are required to install modern Python versions with pyenv. \
	See https://github.com/pyenv/pyenv/wiki/Common-build-problems#build-failed-error-the-python-zlib-extension-was-not-compiled-missing-the-zlib \
	Specifically where it says "If you are using Ubuntu/Debian, you need the following packages:" \
	This will be installed in an ephemeral location, but it's only needed to install Python the first time, so this is fine.
	@echo "${C3_STANDARDS_PREFIX} Installing pyenv dependencies";
	@sudo apt-get update > /dev/null;
	@sudo apt-get install -qq ${PYENV_DEPS} > /dev/null;

	@if ! pyenv versions | grep -Fq ${PYENV_PYTHON_VERSION}; then \
		echo "${C3_STANDARDS_PREFIX} Installing Python ${PYENV_PYTHON_VERSION} for local use. This may take a few minutes."; \
		pyenv install ${PYENV_PYTHON_VERSION} > /dev/null; \
	fi

# Set local Python version of the repository to 3.9. All pip packages will be installed for this specific Python version. \
	Anything outside the repository will default to the system installation.
	@echo "${C3_STANDARDS_PREFIX} Setting local Python version to ${PYENV_PYTHON_VERSION}";
	@cd .. && pyenv local ${PYENV_PYTHON_VERSION};

# Define the `cleanup` target that runs the cleanup playbook.
cleanup:
	ansible-playbook playbooks/cleanup.yml -K

# Define the `setup` target that runs the cleanup and setup playbooks.
setup: cleanup setup_internal

# Define the `setup_internal` target that runs the setup playbook.
setup_internal:
	mkdir -p $(NVM_DIR)
	ansible-playbook playbooks/setup.yml

# Define the `install` target that runs the install playbook.
install:
	ansible-playbook playbooks/install.yml

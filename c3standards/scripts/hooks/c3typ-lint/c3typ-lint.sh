#!/usr/bin/env bash

# Script for linting c3typ files. Includes the following features:
# - Identifying missing Type, field and method documentation.

RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD_FONT=$(tput bold)
NORMAL_FONT=$(tput sgr0)

# Get the directory of the current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Boolean to indicate atleast one issue was found in provided files.
ISSUE_FOUND=0

for FILE in "$@"; do
    TYPE_NAME=$(echo "$FILE" | sed 's|.*/||' | sed 's|\.c3typ$||')

    # Warn about undocumented fields/methods.
    UNDOCUMENTED_FIELDS=$(
        # Remove empty lines
        grep -v "^\s*$" "$FILE" |
        # Pre-process the c3typ file
        perl "$SCRIPT_DIR/preprocess_c3typ_file.pl" |
        # Remove all empty lines
        grep -v '^$' |
        # Run perl script to identify missing documentation
        perl "$SCRIPT_DIR/identify_undocumented_fields.pl" "$TYPE_NAME" |
        # Print the output
        awk -F':' '{print $1}'
    )

    if [ -n "$UNDOCUMENTED_FIELDS" ]; then
        echo -e "${RED}[Error] Missing documentation in $TYPE_NAME.c3typ${NC}"
        echo "$UNDOCUMENTED_FIELDS"
        echo ""
        ISSUE_FOUND=1
    fi
done

exit $ISSUE_FOUND

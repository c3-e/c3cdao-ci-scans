#!/bin/bash

# Run pylint and capture its output
output=$(pylint "$@")

# Capture the exit status of pylint
exit_status=$?

# Check the exit status for fatal, error and convention issues
# See https://pylint.pycqa.org/en/latest/user_guide/usage/run.html#exit-codes for more details
if [ $((exit_status & 1)) -ne 0 ] || [ $((exit_status & 2)) -ne 0 ] || [ $((exit_status & 16)) -ne 0 ]; then
    echo "Pylint found critical issues (Check issues with IDs starting with E (Error), F (Fatal) and C (Convention)):"
    echo "$output"
    exit 1
# Else if the exit status is not 0, but there are no fatal, error or convention issues, then there are only warnings
elif [ $exit_status -ne 0 ]; then
    echo "Pylint found warnings:"
    echo "$output"
    exit 0
else
    exit 0
fi

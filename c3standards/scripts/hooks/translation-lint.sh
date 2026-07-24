#!/usr/bin/env bash

ISSUE_FOUND=0

TMPFILE=$(mktemp -t XXX.csv)
echo -e "Alphabetizing translation files.\n"
for FILE in "$@"; do
head -n 1 $FILE > $TMPFILE
cat $FILE | (read; cat) | LC_ALL=C sort | uniq >> $TMPFILE
mv $TMPFILE $FILE
DUPLICATES=$(cat $FILE | (read; cat) | LC_ALL=C sort | uniq | awk -F "," '{ print $1 }' | uniq -c | grep -v '^[[:space:]]*1[[:space:]]' | awk '{print $2}')
if [ -n "$DUPLICATES" ]; then
    ISSUE_FOUND=1
    echo -e "Duplicate translation keys found in $FILE. Please remove duplicates and re-commit"
    for DUPLICATE in $DUPLICATES; do
    echo -e $DUPLICATE
    done
else
    echo -e "\t$FILE"
fi
done
echo ""

exit $ISSUE_FOUND

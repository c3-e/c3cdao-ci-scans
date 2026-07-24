#!/usr/bin/perl
# use strict;
use warnings;

# Read the entire input from standard input.
my $input = do { local $/; <STDIN> };

# This script pre-processes the c3typ in 3 steps.
# Step 1: Process multi-line annotations, convert them to single-line annotations and remove them.
$input =~ s/(@\w+\((?:[^()]++|(?1))*\))//g;

# Step 2: Convert multi-line function declarations into a single line.
# The documentation checker assumes all attribute declarations are defined on a single line.
# This steps converts multi-line function definitions in a single line.
$input =~ s/([a-zA-Z_][a-zA-Z0-9_]*):\s*(\w+\s+)*function(?:<.*>)?\((?:[^()]++|(?1))*\)(.*)/$1: function()/g;

# Step 3: Remove multi-line json object defaults.
# The default values defined for a field are inconsequential to the documentation checker.
# This step removes multi-line json object default defined for an attribute.
$input =~ s/([a-zA-Z_][a-zA-Z0-9_]*):\s*(\w+)\s*=\s*(\{(?:[^{}]++|(?1))*\})/$1 . ": " . $2/ge;

# Print the processed content to standard output.
print $input;

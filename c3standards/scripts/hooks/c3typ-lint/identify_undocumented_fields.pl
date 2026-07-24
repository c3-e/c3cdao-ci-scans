#!/usr/bin/perl
use strict;
use warnings;

###############################################################################################
# Input arguments
###############################################################################################
# The first argument of this script is expected to be the type name of the .c3typ file for
# which linting was run.
my $type_name = $ARGV[0];
my $input = do { local $/; <STDIN> };

###############################################################################################
# Regex constants
###############################################################################################
# Documentation regex constant. Identifies "/**" which is the opening brace for jsdocs.
my $DOCUMENTATION_REGEX = qr/^\s*\/\*\*/;

# Type regex constant. Identifies any line which starts with a letter and includes
# the "type" keyword. Example: "enum type TypeA", "entity type TypeA" etc.
my $TYPE_DECLARATION_REGEX = qr/^(\s*\w*)*\b.*\btype\b/;

# Remix regex constant. Identifies any line which starts with a letter and includes the
# "remix" keyword.
my $REMIX_TYPE_DECLARATION_REGEX = qr/\bremix\b/;

# Enum regex constant. Identifies any line which starts with a letter and includes the
# "enum" keyword.
my $ENUM_TYPE_DECLARATION_REGEX = qr/\benum\b/;

# Regular field/method identifier regex. Looks for field/method declarations by match
# <word> followed by a ":". For instance, `fieldA: string`, `methodA: function()..`
my $REGULAR_FIELD_REGEX = qr/^\s*(\w+):/;

# Enum constant identifier regex. Looks for enum field declarations by match
# <word> followed by a "=". For instance, `OPTION = 'Option'`
my $ENUM_FIELD_REGEX = qr/^\s*(\w+)\s*=/;


###############################################################################################
# Functions
###############################################################################################

# Function to parse through Type file and identify:
# $block_content: The content inside the `{}` of a Type file.
# $pre_block_content: The content before the 'type' declaration in a Type file.
# $is_remix_type: Boolean to indicate whether this is remixed Type.
# $is_enum_type: Boolean to indicate whether this is enum Type.
sub parse_type_file {
  my ($input) = @_;

  # Split the input into lines
  my @lines = split /\n/, $input;

  my $is_remix_type = 0;
  my $is_enum_type = 0;
  my $in_type_block = 0;
  my $in_brace_block = 0;
  my $brace_count = 0;

  # Content before the Type declaration scope
  my $pre_block_content = "";

  # Content inside the Type declaration scope
  my $block_content = "";

  foreach my $line (@lines) {
    $line =~ s/^\s+//;

    # Step 1: Identify the first line containing "type" followed by a space.
    if (!$in_type_block) {
      $pre_block_content .= "$line\n";
      if ($line =~ $TYPE_DECLARATION_REGEX) {
        $is_remix_type = $line =~ $REMIX_TYPE_DECLARATION_REGEX;
        $is_enum_type = $line =~ $ENUM_TYPE_DECLARATION_REGEX;
        $in_type_block = 1;
      }
    }

    # Step 2: Once in_type_block is true, look for opening and closing braces.
    if ($in_type_block) {
      # Increment brace_count on opening brace, decrement on closing brace.
      $brace_count += ($line =~ tr/{//);
      $brace_count -= ($line =~ tr/}//);

      # If inside the brace block and there is brace count > 0, add to content.
      if ($in_brace_block && $brace_count != 0) {
        $block_content .= "$line\n";
      }

      # If in the brace block and brace count is 0, terminate the loop.
      if ($in_brace_block && $brace_count == 0) {
        last;
      }

      # If $in_brace_block is not 1 but there is one brace count, set $in_brace_block to 1.
      # We do this because the opening brace for a Type doc could be on a different line.
      if (!$in_brace_block && $brace_count == 1) {
        $in_brace_block = 1;
      }
    }
  }

  return ($block_content, $pre_block_content, $is_remix_type, $is_enum_type);
}

# Function to identify missing Type documentation.
# Assumptions:
# - There's always a space between the copyright header, if it exists, and the Type
#   documentation - this is the default behavior in the platform formatter.
# - Only passed in the content before the "type" declaration.
sub identify_missing_type_documentation {
  my ($pre_block_content, $is_remix_type) = @_;
  my @block_lines = split /\n/, $pre_block_content;
  my $documentation_bit = 0;

  foreach my $line (@block_lines) {
    $line =~ s/^\s+//;

    # If the documentation bit is true but we encounter a new line, set it back to false.
    if ($documentation_bit && $line =~ /^\s*$/ ) {
      $documentation_bit = 0;
      next;
    }

    # If we encounter a documentation opener, set documentation bit to true.
    if ($line =~ $DOCUMENTATION_REGEX) {
      $documentation_bit = 1;
      next;
    }

    # If parsing the type declaration and the documentation bit is not true, print to throw error.
    if ($line =~ $TYPE_DECLARATION_REGEX) {
      if (!$is_remix_type && !$documentation_bit) {
        print "- $type_name$1 type\n";
      }
      $documentation_bit = 0;
    }
  }
}

# Function to identify missing field/method documentation.
# Assumptions:
# - Only passed in the content inside the type declaration scope.
# - No empty lines.
sub identify_missing_field_documentation {
  my ($block_content, $is_enum_type) = @_;
  my @block_lines = split /\n/, $block_content;
  my $documentation_bit = 0;

  # Use regular or enum field identifier based on the type.
  my $field_identifier = $is_enum_type ? $ENUM_FIELD_REGEX : $REGULAR_FIELD_REGEX;

  foreach my $line (@block_lines) {
    $line =~ /^\s+/;

    # If we encounter a documentation opener, set documentation bit to true.
    if ($line =~ $DOCUMENTATION_REGEX) {
      $documentation_bit = 1;
      next;
    }

    if ($line =~ $field_identifier) {
      # If the field is not inherited and the documentation bit is not true when we reach
      # the field declaration, print to throw error.
      my $is_inherited = $line =~ /~/;
      if (!$is_inherited && !$documentation_bit) {
        print "- $1\n";
      }
      $documentation_bit = 0;
    }
  }
}

my ($block_content, $pre_block_content, $is_remix_type, $is_enum_type) = parse_type_file($input);
identify_missing_type_documentation($pre_block_content, $is_remix_type);
identify_missing_field_documentation($block_content, $is_enum_type);

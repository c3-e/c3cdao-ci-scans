/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/* eslint-disable import/no-extraneous-dependencies, import/extensions */
const fs = require('fs');
const tmpDir = process.argv[2];
const { mergeDevDependencies } = require('./c3standardsHelper.js');

// Variables for `package.json` creation
const name = process.argv[3];
const description = process.argv[4];

var modifiedPkg;

// Collect base `package.json` from c3standards
const basePkg = JSON.parse(fs.readFileSync(`${tmpDir}/package.json`, 'utf-8'));

if (process.argv.length > 3) {
  // If name/description were passed, create a custom package.json
  modifiedPkg = { ...basePkg, name, description };
} else {
  const currentPkg = JSON.parse(fs.readFileSync('package.json', 'utf-8'));
  modifiedPkg = mergeDevDependencies(currentPkg, basePkg);
}

// Write to `package.json`
fs.writeFileSync('package.json', JSON.stringify(modifiedPkg, null, 2));

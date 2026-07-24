/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/* eslint-disable import/no-extraneous-dependencies, import/no-dynamic-require, import/extensions */
const fs = require('fs');
const { parse } = require('jsonc-parser');
const _ = require('lodash');
const { getConfigDiff } = require('./c3standardsHelper.js');

var configs = ['eslintrc', 'stylelintrc'];

_.forEach(configs, (config) => {
  var base = require(`../../config/${config}.base.js`);
  var overrides = {};

  if (!fs.existsSync(`.${config}`)) {
    var finalExtends = [`require.resolve('./c3standards/config/${config}.base.js')`];
  } else {
    var raw = fs.readFileSync(`./.${config}`, 'utf-8');
    var current = parse(raw);

    var baseExtends = base.extends || [];
    var currentExtends = current.extends || [];

    var newExtends = currentExtends.filter((e) => !baseExtends.includes(e));

    var finalExtends = [`require.resolve('./c3standards/config/${config}.base.js')`, ...newExtends];

    overrides = getConfigDiff(base, current, config);
  }

  var finalConfig = {
    extends: finalExtends,
    ...overrides,
  };

  var output = `module.exports = ${JSON.stringify(finalConfig, null, 2).replace(/"require\.resolve\((.*?)\)"/g, 'require.resolve($1)')};\n`;

  fs.writeFileSync(`.${config}.js`, output);
});

var basePrettier = require(`../../config/prettierrc.base.js`);
var currentPrettier = parse(fs.readFileSync(`./.prettierrc`, 'utf-8'));
var prettierOverrides = getConfigDiff(basePrettier, currentPrettier, 'prettierrc');

var output = `module.exports = {
  ...require('./c3standards/config/prettierrc.base'),
  ${Object.entries(prettierOverrides)
    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
    .join(',\n  ')}
};\n`;
fs.writeFileSync(`.prettierrc.js`, output);

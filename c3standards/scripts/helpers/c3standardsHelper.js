/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/* eslint-disable import/no-extraneous-dependencies, no-continue */
var _ = require('lodash');

/**
 *  Function to merge two different Package.json development dependencies.
 * @param currentPkg The current package.json at root
 * @param newPkg The updated package.json from c3standards
 * @returns The combined development dependencies
 */
function mergeDevDependencies(currentPkg, newPkg) {
  const { name, description, devDependencies: currentDevDeps } = currentPkg;
  const { devDependencies: baseDevDeps } = newPkg;

  const dependencyMap = Object.keys(currentDevDeps).reduce((acc, dep) => {
    if (!baseDevDeps[dep]) {
      acc[dep] = currentDevDeps[dep];
    }
    return acc;
  }, {});

  const devDependencies = { ...baseDevDeps, ...dependencyMap };

  const modifiedPkg = { ...currentPkg, ...newPkg, name, description, devDependencies };

  return modifiedPkg;
}

/**
 *  Function to help find specific changes from the base configuration
 *  against the one located at root.
 * @param baseOverrides The base override configuration
 * @param currentOverrides The current override configuration
 * @param config The type of linter configuration (eslint, stylelint, prettier)
 * @returns The different fields from two overrides
 */
function diffOverrides(baseOverrides, currentOverrides, config) {
  var diffed = [];

  for (const currentOverride of currentOverrides) {
    // This specific override is forcefully skipped in order to maintain functionality
    if (config === 'prettierrc' && currentOverride.options.parser === 'json') continue;

    // Find an override on the base config that has the same `files` key.
    var baseOverride = _.find(baseOverrides, (baseOverr) => _.isEqual(baseOverr.files, currentOverride.files));

    if (!baseOverride || !_.isEqual(baseOverride, currentOverride)) {
      diffed.push(currentOverride);
    }
  }
  return diffed;
}
/**
 * Function that compares two different linter configurations and
 * creates a new config file for c3standards 8.9+
 * @param baseLinterConfig The base linter configuration
 * @param currentLinterConfig The current linter configuration
 * @param linterConfig Type of linter configuration (eslint, stylelint, prettier)
 * @returns The overrides with all the differences between base and current configs
 */
function getConfigDiff(baseLinterConfig, currentLinterConfig, linterConfig) {
  var result = {};

  for (const key in currentLinterConfig) {
    // Extends are skipped since they are directly manipulated
    if (key === 'extends') continue;

    if (key === 'overrides') {
      var overridesDiff = diffOverrides(
        baseLinterConfig.overrides || [],
        currentLinterConfig.overrides || [],
        linterConfig
      );
      if (overridesDiff.length > 0) {
        result[key] = overridesDiff;
      }
      continue;
    }

    // Collect each `key` value from the base and the current config
    var baseVal = baseLinterConfig[key];
    var currentVal = currentLinterConfig[key];

    /**
     * If both values are objects, we run the `getConfigDiff` function
     * and save the difference if there is one.
     */
    if (_.isObject(currentVal) && !Array.isArray(currentVal) && _.isObject(baseVal) && !Array.isArray(baseVal)) {
      var nestedDiff = getConfigDiff(baseVal, currentVal, linterConfig);
      if (!_.isEmpty(nestedDiff)) {
        result[key] = nestedDiff;
      }

      // If both values are arrays, they must exactly match. If not, then save the difference.
    } else if (Array.isArray(currentVal) && Array.isArray(baseVal)) {
      if (!_.isEqual(baseVal, currentVal)) {
        result[key] = currentVal;
      }
    } else {
      if (!_.isEqual(baseVal, currentVal)) {
        result[key] = currentVal;
      }
    }
  }

  return result;
}

module.exports = { mergeDevDependencies, getConfigDiff, diffOverrides };

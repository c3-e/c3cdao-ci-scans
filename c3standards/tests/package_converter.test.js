/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/* eslint-disable import/extensions */
const { mergeDevDependencies } = require('../scripts/helpers/c3standardsHelper.js');

describe('mergeDevDependencies', () => {
  test('merges missing devDependencies from base package.json into the current one', () => {
    const currentPkg = {
      name: 'currentPackage',
      description: 'Current Package Description',
      devDependencies: {
        eslint: '^8.0.0',
      },
    };

    const basePkg = {
      name: 'basePackage',
      description: 'Base Package Description',
      devDependencies: {
        jest: '^29.0.0',
        lodash: '^4.17.21',
      },
    };

    const result = mergeDevDependencies(currentPkg, basePkg);

    expect(result.name).toBe('currentPackage');
    expect(result.description).toBe('Current Package Description');
    expect(result.devDependencies).toEqual({
      eslint: '^8.0.0',
      lodash: '^4.17.21',
      jest: '^29.0.0',
    });
  });

  test('packages with the same dependencies should get updated ', () => {
    const currentPkg = {
      name: 'currentPackage',
      description: 'Current Package Description',
      devDependencies: {
        prettier: '^2.0.0',
      },
    };

    const basePkg = {
      devDependencies: {
        prettier: '^3.0.0',
      },
    };

    const result = mergeDevDependencies(currentPkg, basePkg);

    expect(result.devDependencies.prettier).toBe('^3.0.0'); //
  });

  test('handles empty devDependencies gracefully', () => {
    const currentPkg = {
      name: 'empty-app',
      description: 'no deps',
      devDependencies: {},
    };

    const basePkg = {
      devDependencies: {},
    };

    const result = mergeDevDependencies(currentPkg, basePkg);

    expect(result.devDependencies).toEqual({});
  });

  test('adds only missing dependencies from current and updates', () => {
    const currentPkg = {
      name: 'custom-app',
      description: 'deps test',
      devDependencies: {
        prettier: '1.0.0',
        json: '2.0.0',
        lint: '3.0.0',
      },
    };

    const basePkg = {
      devDependencies: {
        prettier: '1.1.0',
        lodash: '9.0.0',
      },
    };

    const result = mergeDevDependencies(currentPkg, basePkg);

    expect(result.devDependencies).toEqual({
      prettier: '1.1.0',
      lodash: '9.0.0',
      json: '2.0.0',
      lint: '3.0.0',
    });
  });
});

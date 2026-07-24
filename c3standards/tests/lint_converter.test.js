/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/* eslint-disable import/extensions */
const { diffOverrides, getConfigDiff } = require('../scripts/helpers/c3standardsHelper.js');

describe('diffOverrides', () => {
  test('returns only changed overrides based on `files` key', () => {
    const base = [{ files: ['*.js'], rules: { semi: 'error' } }];
    const current = [
      { files: ['*.js'], rules: { semi: 'warn' } },
      { files: ['*.ts'], rules: { quotes: 'error' } },
    ];
    const result = diffOverrides(base, current, 'eslintrc');

    expect(result).toEqual([
      { files: ['*.js'], rules: { semi: 'warn' } },
      { files: ['*.ts'], rules: { quotes: 'error' } },
    ]);
  });

  test('skips prettierrc overrides with parser json', () => {
    const base = [];
    const current = [{ files: ['*.json'], options: { parser: 'json' } }];
    const result = diffOverrides(base, current, 'prettierrc');
    expect(result).toEqual([]);
  });
});

describe('getConfigDiff', () => {
  test('ignores `extends` key', () => {
    const base = { extends: ['base'], rules: { semi: 'error' } };
    const current = { extends: ['custom'], rules: { semi: 'warn' } };
    const result = getConfigDiff(base, current, 'eslintrc');

    expect(result).toEqual({ rules: { semi: 'warn' } });
  });

  test('detects override differences', () => {
    const base = {
      overrides: [{ files: ['*.js'], rules: { eqeqeq: 'error' } }],
    };
    const current = {
      overrides: [
        { files: ['*.js'], rules: { eqeqeq: 'warn' } },
        { files: ['*.ts'], rules: { quotes: 'error' } },
      ],
    };
    const result = getConfigDiff(base, current, 'eslintrc');

    expect(result).toEqual({
      overrides: [
        { files: ['*.js'], rules: { eqeqeq: 'warn' } },
        { files: ['*.ts'], rules: { quotes: 'error' } },
      ],
    });
  });

  test('returns only changed array keys', () => {
    const base = {
      plugins: ['a'],
    };
    const current = {
      plugins: ['a', 'b'],
    };

    const result = getConfigDiff(base, current, 'eslintrc');
    expect(result).toEqual({ plugins: ['a', 'b'] });
  });

  test('returns empty object when configs match', () => {
    const base = { rules: { semi: 'error' } };
    const current = { rules: { semi: 'error' } };
    const result = getConfigDiff(base, current, 'eslintrc');

    expect(result).toEqual({});
  });
});

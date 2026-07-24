/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

module.exports = {
  extends: ['eslint:recommended', 'plugin:@c3-e/eslint-plugin/style-guide-prettier', 'prettier'],

  // By default, eslint ignores folders that start with a dot. Explicitly lint c3 specific folders.
  ignorePatterns: ['!.jarvis'],
  parserOptions: {
    ecmaVersion: 2022,
  },
  overrides: [
    {
      files: ['.jarvis/**/*.{js,ts}', '**/metadata/**/*.{js,ts}'],

      /*
       * Jarvis steps and canonicals/transforms do not support modern JS syntax and are sometimes
       * interpreted by the expression engine, not a JS parser. Disable some rules that could cause
       * errors for these files.
       */
      parserOptions: {
        ecmaVersion: 2015,
      },
      rules: {
        eqeqeq: 'off',
        'logical-assignment-operators': ['error', 'never'],
        'object-shorthand': ['error', 'never'],
        'operator-assignment': ['error', 'never'],
        'prefer-arrow-callback': 'off',
        'prefer-destructuring': 'off',
        'prefer-exponentiation-operator': 'off',
        'prefer-object-spread': 'off',
        'prefer-spread': 'off',
        'prefer-template': 'off',
      },
    },
    {
      files: ['test_*.{js,jsx}'],
      plugins: ['jasmine'],
      env: {
        jasmine: true,
      },
      extends: [
        // Extend the base jasmine rules
        'plugin:@c3-e/eslint-plugin/jasmine',
      ],
    },
    {
      files: ['test_*.{ts,tsx}'],
      plugins: ['jasmine'],
      env: {
        jasmine: true,
      },
      parser: '@typescript-eslint/parser',
      extends: [
        // Extend the base jasmine and typescript rules
        'plugin:@c3-e/eslint-plugin/jasmine',
        'plugin:@c3-e/eslint-plugin/typescript',
      ],
    },
    {
      files: ['**/{/test,}/src/**/*.tsx'],
      parserOptions: {
        sourceType: 'module',
        ecmaFeatures: {
          jsx: true,
        },
      },
      settings: {
        react: {
          version: '16.9.0',
        },
      },
      extends: [
        // Extend the base typescript rules
        'plugin:@c3-e/eslint-plugin/typescript',
      ],
    },
    {
      files: ['**/{/test,}/src/**/*.jsx'],
      parserOptions: {
        requireConfigFile: false,
        babelOptions: {
          presets: [
            // Set "debug" to `true` to print the list of plugins used
            ['@babel/preset-env', { debug: false }],
            '@babel/preset-react',
          ],
        },
      },
      extends: [
        // Extend the base react rules
        'plugin:@c3-e/eslint-plugin/jsx-template',
      ],
    },
    {
      files: ['**/{/test,}/src/**/*.ts'],
      parser: '@typescript-eslint/parser',
      extends: [
        // Extend the base typescript rules
        'plugin:@c3-e/eslint-plugin/typescript',
      ],
    },
  ],
};

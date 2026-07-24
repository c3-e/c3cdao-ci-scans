#!/usr/bin/env node
/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

const fs = require('fs');

/**
 * Logs an error message and terminates the process with exit code 1.
 * @param {string} msg - The error message to display.
 * @returns {never}
 */
function fail(msg) {
  console.error(`❌ ${msg}`);
  process.exit(1);
}

/**
 * Logs an informational message to stdout.
 * @param {string} msg - The message to display.
 */
function info(msg) {
  console.log(`ℹ️  ${msg}`);
}

/**
 * Validates that a PR's referenced Jira tickets have an allowed priority (P0/P1)
 * and an allowed issue type. Designed to run as a GitHub Actions check on
 * pull_request/pull_request_target events.
 *
 * Required environment variables:
 *  - GITHUB_EVENT_PATH – path to the GitHub event JSON payload
 *  - GITHUB_REPOSITORY – owner/repo string
 *  - JIRA_BASE_URL – base URL of the Jira instance
 *  - JIRA_EMAIL – Jira service account email
 *  - JIRA_API_TOKEN – Jira API token for Basic auth
 *  - ALLOWED_PRIORITIES (optional) – comma-separated priority names
 */
(async () => {
  const {
    GITHUB_EVENT_PATH,
    GITHUB_REPOSITORY,
    JIRA_BASE_URL,
    JIRA_EMAIL,
    JIRA_API_TOKEN,
    ALLOWED_PRIORITIES = 'P0 - Blocker,P1 - Urgent with no workaround',
  } = process.env;

  if (!GITHUB_EVENT_PATH || !fs.existsSync(GITHUB_EVENT_PATH)) {
    fail(
      'GITHUB_EVENT_PATH is missing or unreadable; this script must run within a GitHub Actions pull_request/pull_request_target event.'
    );
  }
  if (!GITHUB_REPOSITORY) {
    fail('GITHUB_REPOSITORY is missing; this script must run within GitHub Actions.');
  }

  if (!JIRA_BASE_URL || !JIRA_EMAIL || !JIRA_API_TOKEN) {
    fail('Jira credentials missing. Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN as repository secrets.');
  }

  // Validate JIRA_BASE_URL format to prevent URL injection
  let jiraBaseUrl;
  try {
    jiraBaseUrl = new URL(JIRA_BASE_URL);
  } catch (e) {
    fail(`Invalid JIRA_BASE_URL format: ${e.message}`);
  }
  if (!['http:', 'https:'].includes(jiraBaseUrl.protocol)) {
    fail(`Invalid JIRA_BASE_URL protocol: ${jiraBaseUrl.protocol}`);
  }
  const jiraBase = jiraBaseUrl.toString().replace(/\/+$/, '');

  const ev = JSON.parse(fs.readFileSync(GITHUB_EVENT_PATH, 'utf8'));
  const pr = ev.pull_request;
  if (!pr) {
    fail(
      'No pull_request found in GitHub event payload; this script is intended to run on pull_request/pull_request_target events.'
    );
  }
  const prNumber = pr.number;
  const baseRef = pr.base && pr.base.ref;
  const title = pr.title || '';

  info(`Checking PR #${prNumber} targeting ${baseRef}`);
  info(`Title: "${title}"`);

  // Extract all Jira keys from the PR title (e.g., ABC-1234, XYZ-56)
  const keyMatches = [...title.matchAll(/\b([A-Z][A-Z0-9]+-\d+)\b/gi)];
  if (keyMatches.length === 0) {
    fail('PR title missing Jira key (expected format like ABC-1234).');
  }
  const issueKeys = [...new Set(keyMatches.map((m) => m[1].toUpperCase()))];
  info(`Found Jira key${issueKeys.length > 1 ? 's' : ''}: ${issueKeys.join(', ')}`);

  const allowed = ALLOWED_PRIORITIES.split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  const jiraAuth = Buffer.from(`${JIRA_EMAIL}:${JIRA_API_TOKEN}`).toString('base64');
  const fields = ['issuetype', 'priority'];

  for (const issueKey of issueKeys) {
    const issueUrl = `${jiraBase}/rest/api/3/issue/${encodeURIComponent(issueKey)}?fields=${fields.join(',')}`;

    let res;
    try {
      res = await fetch(issueUrl, {
        headers: {
          Authorization: `Basic ${jiraAuth}`,
          Accept: 'application/json',
        },
      });
    } catch (e) {
      fail(`Network error while fetching Jira issue ${issueKey}: ${e.message}`);
    }

    if (res.status === 404) {
      fail(`Jira issue ${issueKey} not found.`);
    }
    if (!res.ok) {
      const txt = await res.text();
      fail(`Jira API error for ${issueKey} (${res.status}): ${txt}`);
    }

    const issue = await res.json();
    const f = issue.fields || {};
    const issueType = f.issuetype && f.issuetype.name ? String(f.issuetype.name) : '';
    const priorityName = f.priority && f.priority.name ? String(f.priority.name).trim() : '';

    info(`${issueKey}: IssueType="${issueType}" | Priority="${priorityName}"`);

    if (!/^bug$/i.test(issueType)) {
      fail(`Jira issue ${issueKey} is not a Bug (found "${issueType || 'unknown'}").`);
    }

    const hit = priorityName && allowed.includes(priorityName.toLowerCase());
    if (!hit) {
      fail(
        `Priority not allowed for ${issueKey} (found "${priorityName || 'unset'}"; allowed: ${ALLOWED_PRIORITIES}).`
      );
    }
    info(`✅ ${issueKey} passes (type="${issueType}" & priority ∈ {${ALLOWED_PRIORITIES}}).`);
  }

  info(`✅ All ${issueKeys.length} ticket${issueKeys.length > 1 ? 's' : ''} passed validation.`);
  process.exit(0);
})();

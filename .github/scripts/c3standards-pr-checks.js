#!/usr/bin/env node
/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/**
 * @file c3standards-pr-checks.js
 * @description Aggregates the results of all PR sub-checks (Jarvis CI, Code Analyzer, P0/P1 policy)
 * into a single `c3standards/pr-checks` commit status using worst-state-wins logic.
 * Designed to run as a GitHub Actions step triggered by `status`, `pull_request`, or `workflow_dispatch` events.
 *
 * Environment variables consumed:
 * - GITHUB_TOKEN (required) — Bearer token for GitHub API calls.
 * - GITHUB_EVENT_PATH — Path to the JSON event payload.
 * - GITHUB_REPOSITORY — "owner/repo" of the current repository.
 * - GITHUB_EVENT_NAME — The triggering event name.
 * - GITHUB_SHA — Fallback commit SHA.
 * - GITHUB_SERVER_URL / GITHUB_RUN_ID — Used to construct the status target URL.
 * - GITHUB_STEP_SUMMARY — Path to write the Markdown job summary.
 * - INPUT_SHA — Optional override SHA (workflow_dispatch input).
 * - JARVIS_PREFIX — Context prefix for Jarvis statuses (default: "continuous-integration/jarvis").
 * - CODE_ANALYSIS_PREFIX — Context prefix for Code Analyzer statuses (default: "C3 AI Code Analyzer").
 * - P0P1_CONTEXT — Context name for the P0/P1 policy check (default: "policy/p0p1").
 * - GATE_CONTEXT — Context name for the aggregated gate status (default: "c3standards/pr-checks").
 */

const fs = require('fs');

/**
 * Logs a fatal error message and terminates the process with exit code 1.
 * @param {string} msg - The error message to display.
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
 * Reads an environment variable, returning a fallback if it is unset or empty.
 * @param {string} name - The environment variable name.
 * @param {string} [fallback] - The value to return when the variable is missing.
 * @returns {string} The environment variable value or the fallback.
 */
function getEnv(name, fallback) {
  const v = process.env[name];
  return v == null || v === '' ? fallback : v;
}

/**
 * Parses a "owner/repo" string into its constituent parts.
 * @param {string} fullName - The full repository name (e.g. "c3-e/c3standards").
 * @returns {{ owner: string, repo: string }} The parsed owner and repository name.
 * @throws {Error} If the format is not exactly "owner/repo".
 */
function parseRepository(fullName) {
  const parts = String(fullName).split('/');
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    throw new Error(`Invalid GITHUB_REPOSITORY: ${fullName}`);
  }
  return { owner: parts[0], repo: parts[1] };
}

/**
 * Makes an authenticated request to the GitHub REST API.
 * @param {string} url - The full GitHub API URL.
 * @param {string} token - A Bearer token for authentication.
 * @param {RequestInit} [options={}] - Additional fetch options (method, body, headers).
 * @returns {Promise<object>} The parsed JSON response body.
 * @throws {Error} If the response status is not 2xx.
 */
async function githubRequest(url, token, options = {}) {
  const r = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(options.headers || {}),
    },
  });

  if (!r.ok) {
    const txt = await r.text();
    throw new Error(`GitHub API error (${r.status}) for ${url}: ${txt}`);
  }
  return r.json();
}

/**
 * Fetches all commit statuses for a given SHA, paginating through all results.
 * @param {string} owner - The repository owner.
 * @param {string} repo - The repository name.
 * @param {string} sha - The commit SHA to query statuses for.
 * @param {string} token - A GitHub API bearer token.
 * @returns {Promise<object[]>} An array of all status objects for the commit.
 */
async function listCommitStatuses(owner, repo, sha, token) {
  const perPage = 100;
  const out = [];

  for (let page = 1; page <= 50; page += 1) {
    const url = `https://api.github.com/repos/${owner}/${repo}/commits/${sha}/statuses?per_page=${perPage}&page=${page}`;
    const batch = await githubRequest(url, token);
    out.push(...batch);
    if (batch.length < perPage) {
      break;
    }
  }

  return out;
}

/**
 * Deduplicates statuses by context, keeping only the most recent status per context.
 * @param {object[]} statuses - Raw status objects from the GitHub API.
 * @returns {Map<string, object>} A map of context name → most recent status object.
 */
function latestByContext(statuses) {
  const map = new Map();
  for (const s of statuses) {
    if (!s || !s.context) {
      continue;
    }
    const existing = map.get(s.context);
    if (!existing) {
      map.set(s.context, s);
      continue;
    }
    const a = new Date(existing.created_at);
    const b = new Date(s.created_at);
    if (b > a) {
      map.set(s.context, s);
    }
  }
  return map;
}

/**
 * Normalizes a GitHub status state string to one of the four canonical values.
 * Unrecognized values default to 'error'.
 * @param {string} state - The raw state string from the API.
 * @returns {'success'|'pending'|'failure'|'error'} The normalized state.
 */
function normalizeState(state) {
  const s = String(state || '').toLowerCase();
  if (s === 'success' || s === 'pending' || s === 'failure' || s === 'error') {
    return s;
  }
  return 'error';
}

/**
 * Returns the worst (most severe) state from an array of normalized states.
 * Severity order: error > failure > pending > success.
 * @param {string[]} states - An array of normalized state strings.
 * @returns {'error'|'failure'|'pending'|'success'} The worst state present.
 */
function worstState(states) {
  // Worst-to-best order.
  const order = ['error', 'failure', 'pending', 'success'];
  for (const candidate of order) {
    if (states.includes(candidate)) {
      return candidate;
    }
  }
  return 'pending';
}

/**
 * Creates a short comma-separated summary string, truncating with "…" if more than 2 items.
 * @param {string[]} items - The items to summarize.
 * @returns {string} A human-readable summary (e.g. "Jarvis, Code Analysis…").
 */
function summarize(items) {
  if (items.length <= 2) {
    return items.join(', ');
  }
  return `${items.slice(0, 2).join(', ')}…`;
}

/**
 * Maps a normalized state to a corresponding emoji for visual output.
 * @param {string} state - A normalized state string.
 * @returns {string} An emoji representing the state.
 */
function stateEmoji(state) {
  switch (state) {
    case 'success':
      return '✅';
    case 'pending':
      return '⏳';
    case 'failure':
      return '❌';
    case 'error':
      return '🚨';
    default:
      return '❓';
  }
}

/**
 * Normalizes free-form text for safe single-line log/summary rendering.
 * @param {string} value - Raw text content from GitHub status fields.
 * @returns {string} Sanitized single-line text.
 */
function sanitizeInlineText(value) {
  return String(value || '')
    .replace(/[\r\n]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Escapes Markdown-sensitive characters for table cell rendering.
 * @param {string} value - Raw text content.
 * @returns {string} Escaped Markdown-safe content.
 */
function escapeMarkdownTableText(value) {
  return sanitizeInlineText(value).replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/`/g, '\\`');
}

/**
 * Renders a safe Markdown inline code span for arbitrary text.
 * Chooses a delimiter longer than any backtick run in the content.
 * @param {string} value - Raw text content.
 * @returns {string} Markdown inline code span.
 */
function renderMarkdownCodeSpan(value) {
  const normalized = sanitizeInlineText(value);
  const runs = normalized.match(/`+/g) || [];
  const longestRun = runs.reduce((max, run) => Math.max(max, run.length), 0);
  const fence = '`'.repeat(longestRun + 1);
  const codeContent = normalized.startsWith('`') || normalized.endsWith('`') ? ` ${normalized} ` : normalized;

  return `${fence}${codeContent}${fence}`;
}

/**
 * Safely formats a status target URL for markdown output.
 * @param {string} value - Raw target_url field value.
 * @returns {string} Markdown link or fallback plain text.
 */
function formatStatusTargetUrl(value) {
  const normalized = sanitizeInlineText(value);
  if (!normalized) {
    return '—';
  }

  try {
    const parsed = new URL(normalized);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return renderMarkdownCodeSpan(normalized);
    }
    const safeUrl = parsed.toString();
    return `[View details](<${safeUrl}>)`;
  } catch {
    return renderMarkdownCodeSpan(normalized);
  }
}

/**
 * Returns a user-facing description of what a check group does and what failures mean.
 * @param {string} name - The group name ("Jarvis", "Code Analysis", or "P0/P1").
 * @returns {string} A plain-English explanation of the group's purpose.
 */
function groupDescription(name) {
  switch (name) {
    case 'Jarvis':
      return 'Jarvis runs the CI/CD build pipeline (build, unit tests, integration tests). Failures here mean your code has build errors or test failures.';
    case 'Code Analysis':
      return 'C3 AI Code Analyzer runs linting (c3-eslint) on your changes and posts inline PR review comments identifying specific errors, warnings, and the violated rules. Failures mean your code has linting or code standard violations.';
    case 'P0/P1':
      return 'Validates that your PR title contains a Jira key (e.g. ABC-1234) linked to an allowed issue type with P0/P1 priority. Only applies to PRs targeting master, release, or support branches.';
    default:
      return '';
  }
}

/**
 * Returns Markdown-formatted remediation steps for a failing check group.
 * @param {string} name - The group name ("Jarvis", "Code Analysis", or "P0/P1").
 * @returns {string} Actionable fix instructions in Markdown.
 */
function groupRemediationAdvice(name) {
  switch (name) {
    case 'Jarvis':
      return '**How to fix:** Check the Jarvis build log to identify the specific failure — investigate build errors or fix failing tests.';
    case 'Code Analysis':
      return '**How to fix:** Look for the PR review comment from C3 AI Code Analyzer — it lists each error with the file, line number, and ESLint rule that was violated. Review and fix each flagged issue.';
    case 'P0/P1':
      return '**How to fix:** Ensure your PR title includes a valid Jira key (e.g. `PLAT-1234`) and that the issue has P0/P1 priority with an allowed type: Bug.';
    default:
      return '';
  }
}

/**
 * Builds a full Markdown job summary for the GitHub Actions summary page.
 * Includes per-group status tables, descriptions, remediation advice, and an explainer.
 * @param {{ name: string, states: string[], contexts: string[] }[]} groups - The check groups with their states and context names.
 * @param {Map<string, object>} latest - Map of context → latest status object (from latestByContext).
 * @param {string} sha - The commit SHA being evaluated.
 * @param {string} gateState - The overall aggregated gate state.
 * @returns {string} The complete Markdown summary string.
 */
function buildJobSummary(groups, latest, sha, gateState) {
  const lines = [];

  lines.push('# c3standards/pr-checks Summary');
  lines.push('');
  lines.push(`**Commit:** \`${sha.slice(0, 8)}\` | **Overall result:** ${stateEmoji(gateState)} \`${gateState}\``);
  lines.push('');
  lines.push('---');
  lines.push('');

  for (const group of groups) {
    const groupState = group.states.length === 0 ? 'pending' : worstState(group.states);
    lines.push(`## ${stateEmoji(groupState)} ${group.name}`);
    lines.push('');
    lines.push(`> ${groupDescription(group.name)}`);
    lines.push('');

    if (group.states.length === 0) {
      lines.push('**Status:** No status reported yet — this check has not started or has not reported back.');
      lines.push('');
    } else {
      lines.push('| Context | State | Details |');
      lines.push('|---------|-------|---------|');
      for (const ctx of group.contexts) {
        const status = latest.get(ctx);
        const st = normalizeState(status.state);
        const safeCtx = renderMarkdownCodeSpan(ctx);
        const safeDesc = status.description ? escapeMarkdownTableText(status.description) : '—';
        const link = formatStatusTargetUrl(status.target_url);
        lines.push(`| ${safeCtx} | ${stateEmoji(st)} ${st} | ${safeDesc} ${link} |`);
      }
      lines.push('');

      if (['failure', 'error'].includes(groupState)) {
        lines.push(groupRemediationAdvice(group.name));
        lines.push('');
      }
    }
  }

  lines.push('---');
  lines.push('');
  lines.push('<details><summary>How does this gate work?</summary>');
  lines.push('');
  lines.push(
    '`c3standards/pr-checks` is a single required check that aggregates the results of all sub-checks (Jarvis, Code Analyzer, P0/P1 policy). It uses **worst-state-wins** logic:'
  );
  lines.push('');
  lines.push('- If **any** sub-check is `error` or `failure` → the gate fails');
  lines.push('- If **any** sub-check is `pending` or missing → the gate stays pending');
  lines.push('- Only when **all** sub-checks are `success` → the gate passes');
  lines.push('');
  lines.push('The gate re-evaluates automatically each time a sub-check updates.');
  lines.push('</details>');

  return lines.join('\n');
}

/**
 * Main entry point. Reads the GitHub event payload, fetches commit statuses,
 * classifies them into groups (Jarvis, Code Analysis, P0/P1), computes the
 * aggregate gate state, publishes it as a commit status, and writes a job summary.
 */
(async () => {
  const { GITHUB_EVENT_PATH, GITHUB_EVENT_NAME, GITHUB_REPOSITORY, GITHUB_SERVER_URL, GITHUB_RUN_ID } = process.env;

  const token = getEnv('GITHUB_TOKEN', '');
  if (!token) {
    fail('GITHUB_TOKEN is missing; cannot query commit statuses or publish c3standards/pr-checks.');
  }
  if (!GITHUB_EVENT_PATH || !fs.existsSync(GITHUB_EVENT_PATH)) {
    fail('GITHUB_EVENT_PATH is missing or unreadable; this script must run within GitHub Actions.');
  }
  if (!GITHUB_REPOSITORY) {
    fail('GITHUB_REPOSITORY is missing; this script must run within GitHub Actions.');
  }

  const jarvisPrefix = getEnv('JARVIS_PREFIX', 'continuous-integration/jarvis');
  const codeAnalysisPrefix = getEnv('CODE_ANALYSIS_PREFIX', 'C3 AI Code Analyzer');
  const p0p1Context = getEnv('P0P1_CONTEXT', 'policy/p0p1');
  const gateContext = getEnv('GATE_CONTEXT', 'c3standards/pr-checks');

  const ev = JSON.parse(fs.readFileSync(GITHUB_EVENT_PATH, 'utf8'));

  // workflow_dispatch inputs are exposed as INPUT_<name> env vars.
  const inputSha = getEnv('INPUT_SHA', '');
  const sha =
    inputSha ||
    (GITHUB_EVENT_NAME === 'pull_request' && ev.pull_request && ev.pull_request.head && ev.pull_request.head.sha) ||
    (GITHUB_EVENT_NAME === 'status' && ev.sha) ||
    getEnv('GITHUB_SHA', '');

  if (!sha) {
    fail('No commit SHA found for this run.');
  }

  info(`Evaluating PR checks for SHA: ${sha}`);
  const { owner, repo } = parseRepository(GITHUB_REPOSITORY);
  const statuses = await listCommitStatuses(owner, repo, sha, token);

  const latest = latestByContext(statuses);
  const contexts = Array.from(latest.keys());

  const jarvisContexts = contexts.filter((c) => c.startsWith(jarvisPrefix));
  const codeAnalysisContexts = contexts.filter((c) => c.startsWith(codeAnalysisPrefix));
  const p0p1Contexts = contexts.filter((c) => c === p0p1Context);

  const jarvisLatestStates = jarvisContexts.map((c) => normalizeState(latest.get(c).state));
  const codeAnalysisLatestStates = codeAnalysisContexts.map((c) => normalizeState(latest.get(c).state));
  const p0p1LatestStates = p0p1Contexts.map((c) => normalizeState(latest.get(c).state));

  const groups = [
    { name: 'Jarvis', states: jarvisLatestStates, contexts: jarvisContexts },
    { name: 'Code Analysis', states: codeAnalysisLatestStates, contexts: codeAnalysisContexts },
    { name: 'P0/P1', states: p0p1LatestStates, contexts: p0p1Contexts },
  ];

  const missing = groups.filter((g) => g.states.length === 0).map((g) => g.name);
  const failed = groups
    .filter((g) => g.states.length > 0 && ['failure', 'error'].includes(worstState(g.states)))
    .map((g) => g.name);
  const pending = groups.filter((g) => g.states.length > 0 && worstState(g.states) === 'pending').map((g) => g.name);

  let state;
  let description;

  const hasError = groups.some((g) => g.states.includes('error'));
  const hasFailure = groups.some((g) => g.states.includes('failure'));

  if (hasError || hasFailure) {
    state = hasError ? 'error' : 'failure';
    description = `Checks failed: ${summarize(failed)}`;
  } else if (missing.length > 0 || pending.length > 0) {
    state = 'pending';
    const waiting = Array.from(new Set([...missing, ...pending]));
    description = `Waiting on: ${summarize(waiting)}`;
  } else {
    state = 'success';
    description = 'All PR checks passed';
  }

  const targetUrl =
    GITHUB_SERVER_URL && GITHUB_RUN_ID
      ? `${GITHUB_SERVER_URL}/${owner}/${repo}/actions/runs/${GITHUB_RUN_ID}`
      : undefined;

  const statusUrl = `https://api.github.com/repos/${owner}/${repo}/statuses/${sha}`;
  await githubRequest(statusUrl, token, {
    method: 'POST',
    body: JSON.stringify({
      state,
      context: gateContext,
      description,
      ...(targetUrl ? { target_url: targetUrl } : {}),
    }),
  });
  info(`Updated ${gateContext} to ${state}.`);

  // Write GitHub Actions Job Summary for end-user visibility.
  const summaryFile = process.env.GITHUB_STEP_SUMMARY;
  if (summaryFile) {
    const summary = buildJobSummary(groups, latest, sha, state);
    fs.appendFileSync(summaryFile, summary + '\n');
    info('Wrote job summary with detailed check breakdown.');
  }

  // Also log detailed status to stdout for workflow log viewers.
  console.log('');
  console.log('─'.repeat(60));
  console.log(`  c3standards/pr-checks → ${state.toUpperCase()}`);
  console.log('─'.repeat(60));
  for (const group of groups) {
    const gs = group.states.length === 0 ? 'not reported' : worstState(group.states);
    console.log(`  ${stateEmoji(gs === 'not reported' ? 'pending' : gs)} ${group.name}: ${gs}`);
    for (const ctx of group.contexts) {
      const status = latest.get(ctx);
      const st = normalizeState(status.state);
      const safeCtx = sanitizeInlineText(ctx);
      const safeDesc = status.description ? ` — ${sanitizeInlineText(status.description)}` : '';
      console.log(`      ${stateEmoji(st)} ${safeCtx}${safeDesc}`);
    }
  }
  console.log('─'.repeat(60));
  console.log('');
})();

/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

data = {
  name: 'registerArtifactsUpstream',
  hookStep: 'buildSummary',
  hookStrategy: 'async',
  value: function (step) {
    // LLM TA Report generation
    var enableLlmTaConfig = Str.toBool(Jarvis.buildConfigValue('enableLlmTestAvoidance')) || false;
    if (enableLlmTaConfig) {
      // Create LLM TA Analytics Report
      var baseFilter = Filter.eq('jarvisBuild', step.jarvisBuild.id);
      var buildMetadataReport = Jarvis.accessData('JarvisService.Report', 'fetch', {
        filter: baseFilter.and().eq('category', 'Build'),
      }).objs[0].metricData;

      var testReports = Jarvis.accessData('JarvisService.Report', 'fetch', {
        filter: baseFilter.and().eq('category', 'Test'),
      }).objs.map((report) => report.data);

      var buildSteps = _.keyBy(
        Jarvis.accessData('JarvisService.Step', 'fetch', {
          filter: baseFilter.and().intersects('name', ['buildInit', 'buildSummary']),
          include: 'stateHistory, name',
        }).objs,
        'name'
      );

      var buildInitTimestamp = buildSteps.buildInit.stateHistory[1].timestamp; // `buildInit` ASSIGNED timestamp
      var buildSummaryTimestamp = buildSteps.buildSummary.stateHistory[3].timestamp; // `buildSummary` DONE timestamp
      var totalBuildTime = Duration.delta(buildInitTimestamp, buildSummaryTimestamp).seconds;

      var llmTaDryRunFlag = step.jarvisBuild.stashFor('llmTaDryRunFlag');
      var isDryRun = Str.toBool(llmTaDryRunFlag.readString()) || false;
      var lineChangeCount = JSON.parse(step.jarvisBuild.stashFor('baseBranchStash').readString()).lineChangeCount;
      var standardTaPackages = JSON.parse(step.jarvisBuild.stashFor('packagesToIncludeStash').readString());

      var buildMetadata = {
        totalBuildTime: totalBuildTime,
        totalMachineTime: buildMetadataReport.totalMachineTime,
        testCasesErrored: buildMetadataReport.testCasesErrored,
        testCases: buildMetadataReport.testCases,
        testCasesPassed: buildMetadataReport.testCasesPassed,
        testCasesFailed: buildMetadataReport.testCasesFailed,
        testCasesSkipped: buildMetadataReport.testCasesSkipped,
        isDryRun: isDryRun,
        lineChangeCount: lineChangeCount,
        buildNumber: step.jarvisBuild.buildNumber,
        standardTaPackages: standardTaPackages,
      };

      var compareFileDiffs = JSON.parse(step.jarvisBuild.stashFor('baseBranchStash').readString()).changedFiles;

      var studioId = C3.env().tags && C3.env().tags.get('c3__studio');
      var timestamp = DateTime.now().toString();

      var llmAnalyticsReport;
      try {
        // The path format is: <bucket-path>/<studio-id>/<jarvis-build-id>/build-results.json
        var filePath = `azure://c3telemetry/engX/llmTestAvoidance/${studioId || 'unknown'}/${step.jarvisBuild.id}/build-results.json`;
        var file = FileSystem.azure().makeFile(filePath);

        file.writeString(
          JSON.stringify({
            buildMetadata: buildMetadata,
            testReports: testReports,
            timestamp: timestamp,
            compareFileDiffs: compareFileDiffs,
          })
        );

        llmAnalyticsReport = Jarvis.Report.make({
          data: {
            fileLink: file.url,
            timestamp: timestamp,
          },
          category: 'LLM TA',
          subcategory: 'Build Results',
        });
      } catch (e) {
        llmAnalyticsReport = Jarvis.Report.make({
          data: {
            errorMessage: `Failed to write Build Results to Azure Storage: ${e.toString()}`,
            timestamp: timestamp,
          },
          category: 'LLM TA',
          subcategory: 'Build Results',
        });
      }

      Jarvis.fileReports([llmAnalyticsReport]);
    }

    var shouldSkipTestsAndAnalysisStash = step.jarvisBuild.stashFor('shouldSkipTestsAndAnalysis');
    var shouldSkipTestsAndAnalysis = Str.toBool(shouldSkipTestsAndAnalysisStash.readString()) || false;

    if (shouldSkipTestsAndAnalysis) {
      var restApi = Jarvis.sourceControlRestApi();

      if (restApi.type().name() === 'GitHubRestApi') {
        var commitStatusMessage =
          'LLM Test Avoidance determined all tests and analysis should be skipped for this build.';
        restApi.restInst.createCommitStatus(
          restApi.orgWithSrcCtrlRepoName,
          step.jarvisBuild.sha,
          'success',
          'C3 AI Code Analyzer',
          commitStatusMessage
        );
      }
    }

    function _registerIfExists(spec, kind, upstreamAhId) {
      var availableArtifacts = ArtifactHub.availableVersions(spec);
      if (availableArtifacts && availableArtifacts.length > 0) {
        ArtifactHub.registerArtifactsUpstream(spec, upstreamAhId);
        return '\n\nSuccessfully registered ' + kind + ' artifacts to ' + upstreamAhId + '.';
      }

      return (
        '\n\nNo ' +
        kind +
        ' artifacts found for this build. Skipping ' +
        kind +
        ' artifact registration. Spec used:\n\n' +
        JSON.stringify(spec, null, 2)
      );
    }

    function _isDocGenEnabled() {
      var generateDocArtifacts = Str.toBool(Jarvis.buildConfigValue('generateDocArtifacts') || 'false');
      var docArtifactGenerationBranches = C3.Array.fromJsonString(
        Jarvis.buildConfigValue('docArtifactGenerationBranches') || '[]'
      );
      var branchMatches = docArtifactGenerationBranches.containsAny(function (branchRegex) {
        return new RegExp('^(' + branchRegex + ')$').test(step.jarvisBuild.branch);
      });

      return generateDocArtifacts && branchMatches;
    }

    var result = Jarvis.Step.Result.make({
      step: step,
      status: Jarvis.Step.Status.SUCCESS,
    });

    if (Str.toBool(Jarvis.branchGroupConfigValue('registerArtifactsUpstream')) !== true) {
      return result.withError("Skipping artifact registration. 'registerArtifactsUpstream' is set to false.");
    }

    var errors = [];

    var upstreamAhConfigName = 'upstreamArtifactHubId';
    var upstreamAhId = Str.unquote(Jarvis.buildConfigValue(upstreamAhConfigName));
    if (!upstreamAhId) {
      errors.push(
        "No '" +
          upstreamAhConfigName +
          "' config found. Please set '" +
          upstreamAhConfigName +
          "' either in config.js or on the branch group."
      );
    }

    // Check if this is a dev build with docgen enabled (special case for DOC_SITE only)
    var isDevBuildWithDocGen = step.jarvisBuild.preReleaseTag === 'dev' && _isDocGenEnabled();
    var isStandardBuild = ['rc', 'stable', 'support'].includes(step.jarvisBuild.preReleaseTag);

    if (!isStandardBuild && !isDevBuildWithDocGen) {
      var errorStr =
        "This build has a '" +
        step.jarvisBuild.preReleaseTag +
        "' pre-release tag. Only 'rc', 'stable', or 'support' artifacts can be registered upstream.\n" +
        "A 'dev' pre-release tag is allowed when docgen is enabled (`generateDocArtifacts` is `true` and the branch matches `docArtifactGenerationBranches`). In this case, only 'DOC_SITE' artifacts will be registered upstream. Docgen is ";

      if (!_isDocGenEnabled()) {
        errorStr = errorStr + 'not ';
      }
      errors.push(errorStr + 'enabled for this build.');
    }

    if (errors.length > 0) {
      return result.withStatus(Jarvis.Step.Status.ERROR).withError('\n' + errors.join('\n'));
    }

    var build = Jarvis.accessData('JarvisService.Build', 'fetch', {
      filter: Filter.eq('id', step.jarvisBuild.id),
      include: 'this, steps.this, steps.result.this',
    }).objs[0];

    var stepStatus = {};
    build.steps
      .sorted((a, b) => {
        return a.retryCount - b.retryCount;
      })
      .each((s) => {
        var firstTry = s.firstTry ? s.firstTry.id : s.id;
        stepStatus[firstTry] = (s.result && s.result.status) || 'PENDING';
      });

    var isRed = false;
    var isYellow = false;
    Object.keys(stepStatus).forEach((k) => {
      if (stepStatus[k] === 'ERROR') {
        isRed = true;
      } else if (stepStatus[k] === 'NON_FATAL_ERROR') {
        isYellow = true;
      }
    });

    var debugMessage = '';
    var isGreen = !isRed && !isYellow;
    if (isGreen) {
      var buildArtifacts = Jarvis.packageArtifactsForBuild(step.jarvisBuild.id);
      if (!isStandardBuild) {
        buildArtifacts = buildArtifacts.filter((a) => a.kind === 'DOC_SITE');
      }
      var groups = _(buildArtifacts)
        .groupBy('name')
        .mapValues((artifactsForPkg) => {
          return _(artifactsForPkg).map('semanticVersion').sortBy().value();
        })
        .value();
      debugMessage =
        debugMessage +
        '\nAttempting to register the following artifacts upstream:\n\n' +
        JSON.stringify(groups, null, 2);

      var baseFilter = Filter.intersects('id', _.map(buildArtifacts, 'id'));

      // IMPORTANT: THIS IS A WORKAROUND TO A BUG, DO NOT COMBINE INTO 1 REQUEST
      var signedSpec = {
        filter: baseFilter.and().eq('kind', ArtifactHub.ArtifactKind.LEGACY_PKG),
      };
      var rootSrcSpec = {
        filter: baseFilter.and().eq('kind', ArtifactHub.ArtifactKind.ROOT_SOURCE),
      };
      var docSiteSpec = {
        filter: baseFilter.and().eq('kind', 'DOC_SITE'),
      };

      // Register ROOT_SOURCE and LEGACY_PKG artifacts (only for non-dev builds)
      if (isStandardBuild) {
        debugMessage =
          debugMessage + _registerIfExists(rootSrcSpec, ArtifactHub.ArtifactKind.ROOT_SOURCE, upstreamAhId);
        Thread.sleep(10000);

        debugMessage = debugMessage + _registerIfExists(signedSpec, ArtifactHub.ArtifactKind.LEGACY_PKG, upstreamAhId);
        Thread.sleep(10000);
      }

      // Handle DOC_SITE artifacts (pre-release tag already validated above)
      debugMessage = debugMessage + _registerIfExists(docSiteSpec, 'DOC_SITE', upstreamAhId);
    } else {
      debugMessage = debugMessage + "\nBuild wasn't green. Skipping artifact registration.";
    }

    return result.withError(debugMessage);
  },
};

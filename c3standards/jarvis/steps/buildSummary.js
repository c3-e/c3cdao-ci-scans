/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

data = {
  name: 'buildSummary',
  value: function (step) {
    function shouldSkipCodeAnalysis(step) {
      var numCodeAnalysisReports = Jarvis.accessData('JarvisService.Report', 'fetchCount', {
        filter: Filter.eq('jarvisBuild', step.jarvisBuild.id)
          .and()
          .eq('category', 'Code Analysis')
          .and()
          .eq('subcategory', 'Package Results'),
      }).count;

      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Found {} code analysis report(s) for build: {}',
        numCodeAnalysisReports,
        step.jarvisBuild.id
      );
      return numCodeAnalysisReports <= 0;
    }

    // Return immediately if code analysis should be skipped.
    if (shouldSkipCodeAnalysis(step)) {
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'No code analysis reports found. Skipping code analysis summary and running default build summary.'
      );
      return JarvisExecutor.Helper.buildSummary(step);
    }

    /**
     * Helper function to get the execution times for code analysis steps.
     */
    function getCodeAnalysisStepDurations(step) {
      var codeAnalysisSteps =
        Jarvis.accessData('JarvisService.Step', 'fetch', {
          filter: Filter.eq('jarvisBuild', step.jarvisBuild.id).and().eq('name', 'codeAnalysis'),
        }).objs || [];

      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Retrieved {} code analysis step(s) for duration calculation.',
        codeAnalysisSteps.length
      );

      var stepsWithDuration = codeAnalysisSteps.map(function (codeAnalysisStep) {
        var durationString = Jarvis.WithStateHistory.make({
          state: codeAnalysisStep.state,
          stateHistory: codeAnalysisStep.stateHistory,
        }).duration();
        var duration = Duration.fromString(durationString);
        return {
          id: codeAnalysisStep.id,
          durationString: durationString,
          duration: duration,
        };
      });
      return stepsWithDuration;
    }

    /**
     * Helper function to get the latest processed report for the base branch in the repository.
     * This function fetches the last 5 most recently completed builds for the base branch to account for
     * non-"success" final states and picks the processed results report for the most recently completed build.
     */
    function getBaseBranchResultsInfo(baseBranch, repositoryUrl) {
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Fetching base branch results for branch: {}, repo: {}',
        baseBranch,
        repositoryUrl
      );
      var baseBranchBuilds = Jarvis.accessData('JarvisService.Build', 'fetch', {
        filter: Filter.intersects('branch', baseBranch)
          .and()
          .eq('state', Jarvis.State.DONE)
          .and()
          .eq('repositoryUrl', repositoryUrl),
        include: 'id',
        order: 'descending(meta.created)',
        limit: 5,
      });

      var baseBranchResults = [];

      // Only attempt to get the processed results if there are any builds corresponding to the base branch.
      if (baseBranchBuilds.count) {
        Jarvis.visualizedLog(
          Logger.Level.INFO,
          'Found {} completed build(s) for base branch: {}',
          baseBranchBuilds.count,
          baseBranch
        );
        var baseBranchBuildIds = _.map(baseBranchBuilds.objs || [], (build) => {
          return build.id;
        });
        var codeAnalysisReports = Jarvis.accessData('JarvisService.Report', 'fetch', {
          filter: Filter.intersects('jarvisBuild', baseBranchBuildIds)
            .and()
            .eq('category', 'Code Analysis')
            .and()
            .eq('subcategory', 'Processed Results'),
          include: 'data',
          order: 'descending(meta.created)',
        }).objs;

        baseBranchResults =
          codeAnalysisReports && codeAnalysisReports[0] && codeAnalysisReports[0].data.codeAnalysisResults;
      }

      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Base branch results retrieved. Has results: {}',
        !!(baseBranchResults && baseBranchResults.length)
      );

      return {
        baseBranch: baseBranch,
        baseBranchResults: baseBranchResults,
      };
    }

    function stashReports(step) {
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Fetching and stashing code analysis package result reports for build: {}',
        step.jarvisBuild.id
      );
      var codeAnalysisReports =
        Jarvis.accessData('JarvisService.Report', 'fetch', {
          filter: Filter.intersects('jarvisBuild', step.jarvisBuild.id)
            .and()
            .eq('category', 'Code Analysis')
            .and()
            .eq('subcategory', 'Package Results'),
          include: 'id, data',
        }).objs || [];

      var results = codeAnalysisReports
        .filter((childReport) => {
          return childReport.data.status === 'success';
        })
        .map((childReport) => {
          return childReport.data.result;
        })
        .toJsonString();

      var codeAnalysisResultsStash = step.jarvisBuild.stashFor('codeAnalysisResults');
      codeAnalysisResultsStash.writeString(results);

      var codeAnalysisReportIds = codeAnalysisReports.map((report) => {
        return report.id;
      });

      Jarvis.removeReports(codeAnalysisReportIds);
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Stashed and removed Code Analysis {} report(s).',
        codeAnalysisReports.length
      );
    }

    try {
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Starting build summary with code analysis for build: {}',
        step.jarvisBuild.id
      );
      // Stash reports to be retrieved in the `codeAnalysisSummary` step.
      stashReports(step);

      var codeAnalysisStash = step.jarvisBuild.stashFor('codeAnalysisMetadata');
      var codeAnalysisMetadata = JSON.parse(codeAnalysisStash.readString());

      var nextSteps = [];

      var codeAnalysisStepsWithDuration = getCodeAnalysisStepDurations(step);

      // Get base branch results to get comparison values.
      var baseBranchResultsInfo = getBaseBranchResultsInfo(
        codeAnalysisMetadata.baseBranch,
        step.jarvisBuild.repositoryUrl
      );

      // Add a step to notify users of the code analysis results.
      var reportResultsToCodeAnalytics = Jarvis.buildConfigValue('reportResultsToCodeAnalytics');
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Creating codeAnalysisSummary step — customPkg: {}, version: {}, baseBranch: {}, reportToAnalytics: {}',
        codeAnalysisMetadata.packageName,
        codeAnalysisMetadata.semanticVersion,
        codeAnalysisMetadata.baseBranch,
        reportResultsToCodeAnalytics
      );
      var codeAnalysisSummaryStep = Jarvis.Step.builder()
        .id(Uuid.create())
        .name('codeAnalysisSummary')
        .input(
          step.input
            .with('baseBranch', codeAnalysisMetadata.baseBranch)
            .with('baseBranchResults', baseBranchResultsInfo.baseBranchResults)
            .with('codeAnalysisStepsWithDuration', codeAnalysisStepsWithDuration)
            .with('customPkgName', codeAnalysisMetadata.packageName)
            .with('customPkgVersion', codeAnalysisMetadata.semanticVersion)
            .with('reportResultsToCodeAnalytics', Str.toBool(reportResultsToCodeAnalytics))
        )
        .next(step.next)
        .jarvisBuild(step.jarvisBuild)
        .maxRetries(3)
        .build();

      nextSteps.push(codeAnalysisSummaryStep);
      Jarvis.addSteps(nextSteps);
      Jarvis.visualizedLog(Logger.Level.INFO, 'Code analysis summary step queued successfully.');
    } catch (e) {
      Jarvis.visualizedLog(Logger.Level.ERROR, 'Failed to instantiate code analysis summary step: {}', e.toString());
      /**
       * Update status check to notify of error and transition to a final-state if the code above fails.
       *
       * We need to resolve these in the custom lambda since doing so through the logic in `baseCodeAnalyzer`
       * would require us to go over the same steps as those that would have failed in the `try` block.
       */
      var restApi = Jarvis.sourceControlRestApi();
      if (restApi.type().name() === 'GitHubRestApi') {
        Jarvis.visualizedLog(
          Logger.Level.WARN,
          'Setting error commit status on GitHub for SHA: {}',
          step.jarvisBuild.sha
        );
        restApi.restInst.createCommitStatus(
          restApi.orgWithSrcCtrlRepoName,
          step.jarvisBuild.sha,
          'error',
          'C3 AI Code Analyzer',
          'There was an error in reporting your code analysis results.'
        );
      }

      // Add the code analysis instantiation error step to surface the error to the user.
      var errorMessage =
        'Failed to instantiate code analysis summary step because of the following error.\\n' + e.toString();
      var codeAnalysisInstErrorStep = Jarvis.Step.builder()
        .id(step.jarvisBuild.id + '-codeAnalysisSummaryInstError')
        .name('c3standardsStepInstError')
        .input(step.input.with('errorMessage', errorMessage))
        .jarvisBuild(step.jarvisBuild)
        .maxRetries(3)
        .build();
      Jarvis.addSteps([codeAnalysisInstErrorStep]);
      Jarvis.visualizedLog(Logger.Level.WARN, 'Added codeAnalysisSummaryInstError step to surface error to user.');
    }

    // This custom step will override the buildSummary step. First, we need to run the build summary as usual.
    Jarvis.visualizedLog(Logger.Level.INFO, 'Running default build summary.');
    return JarvisExecutor.Helper.buildSummary(step);
  },
};

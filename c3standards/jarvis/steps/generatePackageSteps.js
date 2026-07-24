/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/**
 * The default `generatePackageSteps` step has the following customizations:
 * - Run test avoidance
 * - Queue codeAnalysisInit step
 * - Queue runBuildValidations step
 *
 * After the steps are queued, the Jarvis pipeline is as below:
 *
 *                            |---> UI bundling (pkg1) ---> test execution (pkg1) ... ---|
 * ... -> codeAnalysisInit ---|                                                          |--> buildSummary
 *                            |---> UI bundling (pkg2) ---> test execution (pkg2) ... ---|
 *
 * Note:
 * - The runBuildValidations step is a blocking step of the codeAnalysisInit step. The codeAnalysisInit step will
 * only start after the runBuildValidations step has completed.
 */
data = {
  name: 'generatePackageSteps',
  value: function (step) {
    var shouldSkipTestsAndAnalysisStash = step.jarvisBuild.stashFor('shouldSkipTestsAndAnalysis');
    var shouldSkipTestsAndAnalysis = Str.toBool(shouldSkipTestsAndAnalysisStash.readString()) || false;

    if (shouldSkipTestsAndAnalysis) {
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'LLM Test Avoidance determined all tests and analysis should be skipped for build: {}',
        step.jarvisBuild.id
      );
      var message =
        'No tests will be run and Code Analysis will be skipped for this build based on the LLM Test Avoidance analysis.';
      Jarvis.visualizedLog(Logger.Level.INFO, message);
      return Jarvis.Step.Result.make({ step: step, status: Jarvis.Step.Status.SUCCESS });
    }

    function getRepoPath(step) {
      var baseDirPath = JarvisExecutor.Helper.baseDirFor(step);
      var repoStash = step.jarvisBuild.stashFor('repository.zip');
      var pkgsPath = step.jarvisBuild.packagesPath;
      return JarvisExecutor.SourceControlManager.unstashRepo(repoStash, baseDirPath, pkgsPath);
    }

    var repoPath = getRepoPath(step);
    Jarvis.visualizedLog(Logger.Level.INFO, 'Starting generatePackageSteps for build: {}', step.jarvisBuild.id);

    /*
     * Retrieve the package declarations from the repository stash. This will include downstream
     * repository packages.
     */
    function getRepositoryPkgDecls() {
      var pkgDeclPaths = JarvisExecutor.SourceControlManager.pkgPaths(repoPath);

      // Get all Pkg.Decl objects from repository
      return Array.from(
        pkgDeclPaths.map((pkgPath) => {
          return Pkg.Decl.fromJsonString(File.fromString(pkgPath).readString());
        })
      );
    }

    var pkgDecls = getRepositoryPkgDecls();
    Jarvis.visualizedLog(Logger.Level.INFO, 'Retrieved {} package declaration(s) from repository.', pkgDecls.length);

    // Function to call a lambda in the `<env>/c3` context. This is required for all calls to the `Pkg.Store` API.
    function callLambdaInEnvContext(lambda) {
      return AnyType.unboxValue(C3.env().c3App().callJson('Lambda', 'call', Lambda.fromJsFunc(lambda)));
    }

    /**
     * Function to validate whether the provided list of packages have an upstream dependency on `jarvisBaseToolkit`.
     *
     * The `generatePackageSteps` step also schedules steps for code analysis initialization, code analysis runs and
     * code analysis summaries. The `codeAnalysisInit` step must use a package that has a dependency on
     * `jarvisBaseToolkit` to ensure the it has access to all the `jarvisBaseToolkit` APIs.
     *
     * @param {string[]} packageNames
     *          The list of packages to validate the `jarvisBaseToolkit` dependency for.
     * @returns {string[]}
     *          List of packages that are neither an upstream nor downstream dependency
     *          of `jarvisBaseToolkit`.
     */
    function getMissingBaseToolkitDependency(packageNames) {
      // Include `jarvisBaseToolkit` to handle scenario where `jarvisBaseToolkit` is being built.
      var baseCodeUpstreamDependencies = callLambdaInEnvContext(() => {
        return Pkg.Store.pkg('jarvisBaseToolkit').dependencyNames().toSet();
      });
      var pkgStoreJarvisBaseToolkitPkgs = callLambdaInEnvContext(() => {
        return Pkg.Store.dependentPkgNames('jarvisBaseToolkit').toSet();
      });

      var pkgsWithMissingBaseToolkitDependency = packageNames
        .toSet()
        .difference(C3.Set.fromJson(['jarvisBaseToolkit']))
        .difference(baseCodeUpstreamDependencies)
        .difference(pkgStoreJarvisBaseToolkitPkgs)
        .toArray('[string]');

      return {
        pkgsWithMissingBaseToolkitDependency: pkgsWithMissingBaseToolkitDependency,
        baseCodeUpstreamDependencies: baseCodeUpstreamDependencies,
      };
    }

    /**
     * Function to throw a validation error with an error message prompting the user to add an upstream dependency on
     * `baseCodeAnalyzer` to get a successful build. Should only be called if `pkgsWithMissingBaseToolkitDependency`
     * is non-empty.
     *
     * @param step
     *          The Jarvis step to throw the validation error for.
     * @param pkgsWithMissingBaseToolkitDependency
     *          The list of packages missing an upstream dependency on `baseCodeAnalyzer`.
     * @returns
     *         `Jarvis.Step.Result` with status set to ERROR and error message prompting user to add
     *         baseToolkit dependency.
     */
    function throwBaseCodeAnalyzerValidationError(step, pkgsWithMissingBaseToolkitDependency) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'Packages missing baseToolkit dependency: {}',
        JSON.stringify(Array.from(pkgsWithMissingBaseToolkitDependency))
      );
      // Post a commit status directing the user to navigate to this step's logs in the Jarvis UI to see the error.
      var commitStatusMessage =
        'Build aborted due to missing dependencies. Please see the `generatePackageSteps` step for more information.';
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
          commitStatusMessage
        );
      }

      /*
       * Prompt to add dependency on `baseToolkit` which is the official released artifact (which in-turn includes)
       * `baseCodeAnalyzer` as an upstream dependency.
       */
      var pkgsWithMissingBaseToolkitDependencyString = [];
      pkgsWithMissingBaseToolkitDependency.each((packageName) => {
        pkgsWithMissingBaseToolkitDependencyString.push('- ' + packageName);
      });
      var errorMessage = [
        'The following packages in this build are missing a dependency on `baseToolkit`: ',
        pkgsWithMissingBaseToolkitDependencyString.join('\\n'),
        '',
        'Please add an implicit/explicit dependency on `baseToolkit` to each of these packages to run a successful build.',
      ].join('\\n');
      Jarvis.visualizedLog(Logger.Level.ERROR, errorMessage);
      return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.NON_RETRYABLE_ERROR).build();
    }

    function getBuildSummaryStep(step) {
      return Jarvis.accessData('JarvisService.Step', 'fetch', {
        filter: Filter.eq('jarvisBuild', step.jarvisBuild.id).and().eq('name', 'buildSummary'),
      }).objs.first().id;
    }

    // Run the `generatePackageSteps` package to queue UI bundling and test steps.
    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'Running default generatePackageSteps helper to queue UI bundling and test steps.'
    );
    var result = JarvisExecutor.Helper.generatePackageSteps(step);

    try {
      var packagesToInclude = C3.Array.fromJsonString(Jarvis.buildConfigValue('packagesToInclude'));
      var serverVersion = SemanticVersion.make(step.serverVersion).toMajorMinor().toString();
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Server version: {}, packagesToInclude count: {}',
        serverVersion,
        packagesToInclude ? packagesToInclude.length : 0
      );

      var buildArtifacts;
      // For builds on server version 8.10 and above, use the new `packageArtifactsForBuild` API.
      if (SemanticVersion.gte(serverVersion, '8.10')) {
        Jarvis.visualizedLog(Logger.Level.INFO, 'Using packageArtifactsForBuild API (server >= 8.10).');
        buildArtifacts = Jarvis.packageArtifactsForBuild(step.jarvisBuild.id);
        buildArtifacts = buildArtifacts.filter((artifact) => {
          return artifact.kind === ArtifactHub.ArtifactKind.LEGACY_PKG;
        });
      } else {
        Jarvis.visualizedLog(Logger.Level.INFO, 'Using ArtifactHub.availableVersions API (server < 8.10).');
        var artifactsFilter = Filter.startsWith('id', step.jarvisBuild.id)
          .and()
          .eq('kind', ArtifactHub.ArtifactKind.LEGACY_PKG);

        /*
         * Query Artifact Hub for the full semantic versions of each package that was generated as part of
         * this build. We only fetch the legacy pkg artifacts to avoid fetching the same artifact multiple times.
         *
         * This filter doesn't respect the packagesToInclude build config because we want the full versions
         * of all built packages even if they weren't run due to test avoidance.
         */
        buildArtifacts = ArtifactHub.availableVersions({ filter: artifactsFilter });
      }

      var packageNameToSemanticVersionMap = buildArtifacts
        .toMap((artifact) => {
          return artifact.name;
        })
        .map((artifact) => {
          return artifact.semanticVersion;
        });

      var packageNames = packageNameToSemanticVersionMap.keys().collect();
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Found {} build artifact(s). Package names: {}',
        packageNames.length,
        JSON.stringify(Array.from(packageNames))
      );

      // If packagesToInclude is defined, only check those packages.
      if (packagesToInclude && packagesToInclude.length > 0) {
        packageNames = packageNames.filter((packageName) => {
          return packagesToInclude.contains(packageName);
        });
      }
      var baseToolkitDependencyMetadata = getMissingBaseToolkitDependency(packageNames);
      var pkgsWithMissingBaseToolkitDependency = baseToolkitDependencyMetadata.pkgsWithMissingBaseToolkitDependency;
      var baseCodeUpstreamDependencies = baseToolkitDependencyMetadata.baseCodeUpstreamDependencies;

      if (pkgsWithMissingBaseToolkitDependency.length) {
        return throwBaseCodeAnalyzerValidationError(step, pkgsWithMissingBaseToolkitDependency);
      }

      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'All packages have baseToolkit dependency. Proceeding with step creation.'
      );

      var codeAnalysisInitStepId = step.jarvisBuild.id + '-codeAnalysisInit';
      var runBuildValidationsStepId = step.jarvisBuild.id + '-runBuildValidations';
      var topLevelCustomerPackage = Str.unquote(Jarvis.buildConfigValue('topLevelCustomerPackage'));
      if (topLevelCustomerPackage === 'null') {
        topLevelCustomerPackage = null;
      }

      var testSteps = Jarvis.accessData('JarvisService.Step', 'fetch', {
        filter: Filter.eq('jarvisBuild', step.jarvisBuild.id).and().eq('name', 'testPackages'),
        include: 'id, previous, input',
      }).objs;

      var uiBundlingSteps = Jarvis.accessData('JarvisService.Step', 'fetch', {
        filter: Filter.eq('jarvisBuild', step.jarvisBuild.id)
          .and()
          .intersects('name', ['generateUiBundles', 'skippingUiBundling']),
      }).objs;

      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Found {} test step(s) and {} UI bundling step(s). topLevelCustomerPackage: {}',
        testSteps ? testSteps.length : 0,
        uiBundlingSteps ? uiBundlingSteps.length : 0,
        topLevelCustomerPackage
      );

      var codeAnalysisInitStepInput;
      packageNames.each((packageName) => {
        /*
         * Store custom package name and artifact to run the code analysis summary step from.
         * For customer repositories from which we want to collect customization reports, the codeAnalysisSummary
         * step must use the configured `topLevelCustomerPackage` to run the analyze code APIs.
         */
        if (
          (!codeAnalysisInitStepInput || topLevelCustomerPackage === packageName) &&
          !baseCodeUpstreamDependencies.contains(packageName)
        ) {
          codeAnalysisInitStepInput = C3.Map.ofStrToAny(
            'pkgName',
            packageName,
            'customPkgName',
            packageName,
            'customPkgVersion',
            packageNameToSemanticVersionMap.get(packageName),
            'packageNameToSemanticVersionMap',
            packageNameToSemanticVersionMap,
            'baseCodeUpstreamDependencies',
            baseCodeUpstreamDependencies,
            'testSteps',
            testSteps,
            'uiBundlingSteps',
            uiBundlingSteps
          );
        }
      });

      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Code analysis init step input — customPkg: {}, customPkgVersion: {}',
        codeAnalysisInitStepInput ? codeAnalysisInitStepInput.get('customPkgName') : 'N/A',
        codeAnalysisInitStepInput ? codeAnalysisInitStepInput.get('customPkgVersion') : 'N/A'
      );

      var buildSummaryStep = getBuildSummaryStep(step);
      var codeAnalysisInitStep = Jarvis.Step.make({
        id: codeAnalysisInitStepId,
        name: 'codeAnalysisInit',
        input: codeAnalysisInitStepInput,
        next: buildSummaryStep,
        maxRetries: 3,
      });

      // Add build validation step.
      var runBuildValidationsStep = Jarvis.Step.make({
        id: runBuildValidationsStepId,
        name: 'runBuildValidations',
        input: C3.Map.fromJson({
          pkgDecls: _.map(pkgDecls, (pkgDecl) => {
            return pkgDecl.toJson();
          }),
        }),
        next: codeAnalysisInitStepId,
        maxRetries: 3,
      });

      Jarvis.addSteps([runBuildValidationsStep, codeAnalysisInitStep]);
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Queued runBuildValidations ({}) and codeAnalysisInit ({}) steps.',
        runBuildValidationsStepId,
        codeAnalysisInitStepId
      );
    } catch (e) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'Failed to instantiate code analysis initialization step: {}',
        e.toString()
      );
      // Queue step to surface instantiation error to the user.
      // eslint-disable-next-line no-redeclare
      var errorMessage =
        'Failed to instantiate code analysis initialization step because of the following error. ' +
        'Please reach out to ENG-X immediately.\\n' +
        e.toString();

      var codeAnalysisInstErrorStep = Jarvis.Step.builder()
        .id(step.jarvisBuild.id + '-codeAnalysisInstErrorStep')
        .name('c3standardsStepInstError')
        .input(step.input.with('errorMessage', errorMessage))
        .jarvisBuild(step.jarvisBuild)
        .build();
      Jarvis.addSteps([codeAnalysisInstErrorStep]);
    }

    var enableLlmTaConfig = Str.toBool(Jarvis.buildConfigValue('enableLlmTestAvoidance')) || false;

    if (enableLlmTaConfig) {
      Jarvis.visualizedLog(Logger.Level.INFO, 'LLM Test Avoidance enabled. Reading LLM TA results from stash.');
      var llmTaStash = step.jarvisBuild.stashFor('llmTaResults');
      var llmTaResults = JSON.parse(llmTaStash.readString());

      // If there are recommendations from LLM TA, overwrite test configurations
      if (Object.keys(llmTaResults).length) {
        Jarvis.visualizedLog(
          Logger.Level.INFO,
          'LLM TA results contain {} package recommendation(s). Overwriting test configurations.',
          Object.keys(llmTaResults).length
        );
        _.each(testSteps, (step) => {
          /*
           * `skippingTestPackages` steps do not have any test config assigned.
           * Only overwrite for steps with test configs (determined by its `groupIndex`)
           */
          var testGroup = step.input.groupIndex;
          if (testGroup) {
            var testPkg = step.input.pkgs[0];
            var testsToRun = llmTaResults[testPkg];
            var testConfig = JSON.parse(Jarvis.buildConfigValue(testGroup));

            var configOverwrite = _.map(testConfig, (batch) => {
              if (testsToRun) {
                return _.filter(batch, (file) => {
                  return testsToRun.some((test) => file.includes(test));
                });
              }

              return [];
            });

            Jarvis.setBuildConfigValue(testGroup, JSON.stringify(configOverwrite));
          }
        });
      } else {
        Jarvis.visualizedLog(Logger.Level.INFO, 'LLM TA results are empty. No test configuration overwriting needed.');
      }
    }
    var stepOutputMessage = result.error || '';
    if (stepOutputMessage) {
      Jarvis.visualizedLog(Logger.Level.INFO, '{}', stepOutputMessage);
    }
    Jarvis.visualizedLog(Logger.Level.INFO, 'Step completed successfully for build: {}', step.jarvisBuild.id);
    return result;
  },
};

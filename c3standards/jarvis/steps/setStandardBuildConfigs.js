/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

/**
 * Enables code analysis and coverage for managed branch groups only.
 * Users can configure branch group options for other branch groups.
 * Standard and LLM test avoidance is also configured here.
 */
data = {
  name: 'setStandardBuildConfigs',
  hookStep: 'stashRepo',
  hookStrategy: 'blocking',
  value: function (step) {
    /*
     * LLM TEST AVOIDANCE
     */
    function getTestStrategiesForAffectedPkgs(affectedPackages) {
      // [{ strategy: string, tests: [string] }]
      var testStrategiesString = Jarvis.buildConfigValue('testStrategies');
      var testStrategies = C3.Array.fromJsonString(testStrategiesString || '[]');

      if (!testStrategies || !affectedPackages.length) {
        return [];
      }

      var TEST_PATTERN = Pkg.Path.TEST_FILE_PATTERN;
      var repositoryFiles = JarvisExecutor.Helper.fs().listFiles(repoPath, -1);

      /*
       * Look specifically for instances where the affected package name is bounded by `/` which would correspond
       * to a directory. This regex ensure no false positives are captured. For instance, `demandForecastingUI` would
       * match if the regex only searches for `demandForecasting`.
       */
      var affectedPackagesRegex = '/(' + affectedPackages.join('|') + ')/';
      var affectedPackageTestFiles = repositoryFiles.files.filter((file) => {
        return !!(file.url.match(affectedPackagesRegex) && file.url.match(TEST_PATTERN));
      });

      var strategiesForAffectedPackages = [];
      _.each(testStrategies, (testStrategy, idx) => {
        var testRegExps = testStrategy.tests;
        if (!testRegExps || !testRegExps.length) {
          return true;
        }

        var validTestRegExps = testRegExps.filter((testRegExp) => {
          var anyFile = affectedPackageTestFiles.findAny((file) => {
            return !!file.url.match(testRegExp);
          });
          return !!anyFile;
        });

        if (!validTestRegExps.length) {
          return true;
        }

        var updatedTestStrategy = C3.Map.fromJson(testStrategy).with('tests', validTestRegExps).toJson();
        strategiesForAffectedPackages.push(updatedTestStrategy);
      });

      return strategiesForAffectedPackages;
    }

    function getRepoPath(step) {
      var baseDirPath = JarvisExecutor.Helper.baseDirFor(step);
      var repoStash = step.jarvisBuild.stashFor('repository.zip');
      var pkgsPath = step.jarvisBuild.packagesPath;
      return JarvisExecutor.SourceControlManager.unstashRepo(repoStash, baseDirPath, pkgsPath);
    }

    var repoPath = getRepoPath(step);

    Jarvis.visualizedLog(Logger.Level.INFO, 'Collected the following repo path: {}', repoPath);

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

    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'Collected the following package declarations: {}',
      JSON.stringify(pkgDecls)
    );

    /**
     * Recursive function to determine if `currentPackage` is affected by at least one package in `modifiedPackages`.
     */
    function hasDependencyOnModifiedPkg(modifiedPackages, dependencyGraph, currentPackage) {
      if (!dependencyGraph[currentPackage]) {
        return false;
      }

      if (modifiedPackages[currentPackage]) {
        return true;
      }

      var hasDependency = false;
      var currentPkgDeps = dependencyGraph[currentPackage];
      _.each(modifiedPackages, (modifiedPkg) => {
        if (currentPkgDeps.containsKey(modifiedPkg)) {
          hasDependency = true;
          return true;
        }
      });

      currentPkgDeps.keys().each((currentPkgDep) => {
        if (hasDependencyOnModifiedPkg(modifiedPackages, dependencyGraph, currentPkgDep)) {
          hasDependency = true;
          return true;
        }
      });
      return hasDependency;
    }

    /**
     * Function to determine the subset of `pkgDecls` that include at least one of packages in `modifiedPackages`
     * in their dependency chain.
     */
    function determineAffectedPkgs(modifiedPackages, pkgDecls) {
      // Build dependency graph of each package.
      var dependencyGraph = {};
      _.each(pkgDecls, (pkgDecl) => {
        var pkgName = pkgDecl.name;
        var dependencies = pkgDecl.dependencies;
        dependencyGraph[pkgName] = dependencies || {};
      });

      /*
       * Initialize affected packages with the modified packages. Determine affected packages by looping through
       * each defined package declaration and determining if they have a modified package in their dependency chain.
       */
      var affectedPkgs = Array.from(modifiedPackages);
      _.each(pkgDecls, (pkgDecl) => {
        var pkgName = pkgDecl.name;
        if (hasDependencyOnModifiedPkg(affectedPkgs, dependencyGraph, pkgName)) {
          affectedPkgs.push(pkgName);
        }
      });

      return _.uniq(affectedPkgs);
    }

    function testAvoidance(step) {
      var jarvisBuild = step.jarvisBuild;
      var testAvoidanceMessage = '';
      var modifiedPackages = new Set();
      var restApi = Jarvis.sourceControlRestApi();
      var fileChangeCount = 0;
      var baseBranch = '';

      Jarvis.visualizedLog(Logger.Level.INFO, 'Source control REST API type: {}', restApi.type().name());

      // Test avoidance is only possible with GitHub currently
      if (restApi.type().name() === 'GitHubRestApi') {
        var gitHub = restApi.restInst;

        // If there is a PR associated with the Build, use the base branch of the PR.
        if (step.jarvisBuild.prUrl) {
          Jarvis.visualizedLog(
            Logger.Level.INFO,
            'PR URL detected: {}. Resolving base branch from PR.',
            step.jarvisBuild.prUrl
          );
          baseBranch = gitHub.pullRequest(restApi.orgWithSrcCtrlRepoName, step.jarvisBuild.prUrl.split('/').pop()).base
            .ref;
        } else {
          Jarvis.visualizedLog(Logger.Level.INFO, 'No PR URL found. Using default branch as base branch.');
          // Otherwise, use the default branch of the repository as the base branch.
          baseBranch = gitHub.repository(restApi.orgWithSrcCtrlRepoName).default_branch;
        }

        Jarvis.visualizedLog(Logger.Level.INFO, 'Base branch resolved to: {}', baseBranch);

        var compareResult = gitHub.compare(restApi.orgWithSrcCtrlRepoName, baseBranch, jarvisBuild.sha);
        var repoDir = jarvisBuild.packagesPath;
        var compareResultFiles = compareResult.files;

        Jarvis.visualizedLog(
          Logger.Level.INFO,
          'GitHub compare returned {} changed files for SHA {}',
          compareResultFiles.length,
          jarvisBuild.sha
        );

        /*
         * The comparison result will only show up to 300 files so test all packages if we reach this limit
         */
        var fileLimit = 300;

        // Using the comparison result, collect the names of packages with modified files
        if (compareResultFiles.length < fileLimit) {
          if (repoDir) {
            compareResultFiles.each(function (file) {
              var filename = file.filename;
              fileChangeCount = fileChangeCount + file.changes;
              if (filename.indexOf(repoDir) === 0) {
                var path = filename.replace(repoDir + '/', '');
                if (path.indexOf('/') > -1) {
                  modifiedPackages.add(path.split('/').shift());
                }
              }
            });
          } else {
            var knownPackageNames = _.map(pkgDecls, 'name');
            _.each(compareResultFiles, function (file) {
              fileChangeCount = fileChangeCount + file.changes;
              var segments = file.filename.split('/');
              _.each(knownPackageNames, function (pkgName) {
                if (_.includes(segments, pkgName)) {
                  modifiedPackages.add(pkgName);
                }
              });
            });
          }
        } else {
          Jarvis.visualizedLog(
            Logger.Level.WARN,
            'File limit of {} reached ({} files changed). Skipping static test avoidance and disabling LLM test avoidance.',
            fileLimit,
            compareResultFiles.length
          );
          testAvoidanceMessage =
            'Static Test avoidance skipped because more than 300 files are different with the base branch: ' +
            baseBranch;

          Jarvis.setBuildConfigValue('enableLlmTestAvoidance', 'false');

          var modifiedPackagesStash = step.jarvisBuild.stashFor('modifiedPackages');
          modifiedPackagesStash.writeString(JSON.stringify([]));

          return {
            testAvoidanceMessage: testAvoidanceMessage,
            llmTaChangeCount: fileChangeCount,
            llmTaFileCount: compareResultFiles.length,
          };
        }

        var baseBranchData = {
          baseBranch: baseBranch,
          lineChangeCount: fileChangeCount,
          changedFiles: compareResultFiles,
        };

        var baseBranchStash = step.jarvisBuild.stashFor('baseBranchStash');
        baseBranchStash.writeString(JSON.stringify(baseBranchData));
      }

      if (modifiedPackages.size > 0) {
        Jarvis.visualizedLog(
          Logger.Level.INFO,
          'Modified packages detected: {}',
          JSON.stringify(Array.from(modifiedPackages))
        );
        // Set the packagesToInclude config value so that only affected packages will be built and tested
        var affectedPackages = determineAffectedPkgs(modifiedPackages, pkgDecls);
        Jarvis.visualizedLog(
          Logger.Level.INFO,
          'Affected packages (including transitive dependents): {}',
          JSON.stringify(affectedPackages)
        );
        Jarvis.setBuildConfigValue('packagesToInclude', JSON.stringify(affectedPackages));

        var packagesToIncludeStash = step.jarvisBuild.stashFor('packagesToIncludeStash');
        packagesToIncludeStash.writeString(JSON.stringify(affectedPackages.sort()));

        // Get test strategies for affected packages.
        var testStrategiesForAffectedPkgs = getTestStrategiesForAffectedPkgs(affectedPackages);
        Jarvis.setBuildConfigValue('testStrategies', Jsn.stringify(testStrategiesForAffectedPkgs));

        testAvoidanceMessage =
          testAvoidanceMessage +
          ('Test avoidance identified the following package changes with base branch ' +
            baseBranch +
            ':' +
            JSON.stringify(Array.from(modifiedPackages)) +
            '\n\nThe following affected packages will be built:\n' +
            _.map(affectedPackages, (affectedPackage) => {
              return '- ' + affectedPackage;
            }).join('\\n') +
            '\n\nThe test strategy was updated to:\n' +
            JSON.stringify(testStrategiesForAffectedPkgs));
      } else {
        Jarvis.visualizedLog(
          Logger.Level.WARN,
          'No modified repository packages found compared to base branch: {}. Running build without test avoidance.',
          baseBranch
        );
        testAvoidanceMessage =
          'Test avoidance was not run because there were no package differences found with base branch: ' +
          baseBranch +
          '.\nSetting build config "enableLlmTestAvoidance" to false to disable LLM Test Avoidance.';

        // Disable LLM test avoidance if there are no package differences.
        Jarvis.setBuildConfigValue('enableLlmTestAvoidance', 'false');
      }

      // Store test avoidance-related metadata for reference in other steps and for debugging.
      var testAvoidanceReport = Jarvis.Report.make({
        data: {
          baseBranch: baseBranch,
          runTestAvoidance: runTestAvoidance,
          testAvoidanceMessage: testAvoidanceMessage,
          modifiedPackages: Array.from(modifiedPackages),
        },
        category: 'Test Avoidance',
        subcategory: 'Metadata',
      });
      Jarvis.fileReports([testAvoidanceReport]);

      var modifiedPackagesStash = step.jarvisBuild.stashFor('modifiedPackages');
      modifiedPackagesStash.writeString(JSON.stringify(Array.from(modifiedPackages)));

      return {
        testAvoidanceMessage: testAvoidanceMessage,
        llmTaChangeCount: fileChangeCount,
        llmTaFileCount: compareResultFiles.length,
      };
    }

    function shouldRunLlmTestAvoidance(llmTaChangeCount, llmTaFileCount, enableLlmTaConfig, llmTaCustomPkgVersion) {
      var shouldRunLlmTa = false;
      var llmTaOutputMessage = '';

      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Evaluating LLM Test Avoidance: enableLlmTaConfig={}, llmTaCustomPkgVersion={}, changeCount={}, fileCount={}',
        enableLlmTaConfig,
        llmTaCustomPkgVersion,
        llmTaChangeCount,
        llmTaFileCount
      );

      if (!enableLlmTaConfig) {
        Jarvis.visualizedLog(Logger.Level.INFO, 'LLM Test Avoidance is disabled by configuration.');
        llmTaOutputMessage = '\n\nLLM Test Avoidance disabled.\n';
        return [shouldRunLlmTa, llmTaOutputMessage];
      }

      if (!llmTaCustomPkgVersion) {
        Jarvis.visualizedLog(
          Logger.Level.WARN,
          'LLM Test Avoidance enabled but missing custom package version (llmTaCustomPkgVersion). Skipping.'
        );
        llmTaOutputMessage =
          '\n\nMissing LLM Test Avoidance custom package version.\nPlease set the "llmTaCustomPkgVersion" build config value with the artifact version.\n';
        return [shouldRunLlmTa, llmTaOutputMessage];
      }

      var llmTaChangeLimit = 2000;
      var llmTaFileLimit = 50;

      if (llmTaChangeCount <= llmTaChangeLimit && llmTaFileCount <= llmTaFileLimit) {
        shouldRunLlmTa = true;
        Jarvis.visualizedLog(
          Logger.Level.INFO,
          'LLM Test Avoidance will run: {} files and {} line changes are within limits ({} files / {} changes).',
          llmTaFileCount,
          llmTaChangeCount,
          llmTaFileLimit,
          llmTaChangeLimit
        );
        llmTaOutputMessage =
          llmTaOutputMessage +
          ('\n\nLLM Test Avoidance enabled. The amount of changed files (' +
            llmTaFileCount +
            ') and total changes (' +
            llmTaChangeCount +
            ') are within the limits.');
      } else {
        Jarvis.visualizedLog(
          Logger.Level.WARN,
          'LLM Test Avoidance skipped: {} files (limit {}) and/or {} changes (limit {}) exceeded thresholds.',
          llmTaFileCount,
          llmTaFileLimit,
          llmTaChangeCount,
          llmTaChangeLimit
        );
        llmTaOutputMessage =
          llmTaOutputMessage +
          ('\n\nLLM Test avoidance skipped because the number of changed files (' +
            llmTaFileCount +
            ') or total changes (' +
            llmTaChangeCount +
            ') exceeded the limit of ' +
            llmTaFileLimit +
            ' files and/or ' +
            llmTaChangeLimit +
            ' changes.');
      }

      return [shouldRunLlmTa, llmTaOutputMessage];
    }

    var testAvoidanceOutputMessage = '';

    try {
      /*
       * Run test avoidance before the `generatePackageSteps` to ensure `packagesToInclude` includes
       * only affected packages.
       */
      var testAvoidanceBranchRegex = Str.unquote(Jarvis.buildConfigValue('testAvoidanceBranchRegex'));
      var runTestAvoidance = step.jarvisBuild.branch.match(testAvoidanceBranchRegex);
      var enableLlmTaConfig = Str.toBool(Jarvis.buildConfigValue('enableLlmTestAvoidance')) || false;
      var llmTaCustomPkgVersion = Jarvis.buildConfigValue('llmTaCustomPkgVersion');

      Jarvis.visualizedLog(Logger.Level.INFO, 'Test avoidance branch regex: {}', testAvoidanceBranchRegex);

      if (runTestAvoidance) {
        Jarvis.visualizedLog(Logger.Level.INFO, 'Test avoidance is enabled. Running test avoidance...');
        var testAvoidanceResult = testAvoidance(step);
        testAvoidanceOutputMessage = testAvoidanceResult.testAvoidanceMessage;

        var [shouldRunLlmTa, llmTaOutputMessage] = shouldRunLlmTestAvoidance(
          testAvoidanceResult.llmTaChangeCount,
          testAvoidanceResult.llmTaFileCount,
          enableLlmTaConfig,
          llmTaCustomPkgVersion
        );

        testAvoidanceOutputMessage = testAvoidanceOutputMessage + llmTaOutputMessage;

        if (shouldRunLlmTa) {
          Jarvis.visualizedLog(Logger.Level.INFO, 'Running LLM Test Avoidance...');
          var customPkgName = 'llmTestAvoidance';
          var customPkgVersion = llmTaCustomPkgVersion;

          // Get the id of the generatePackageSteps step for the current jarvisBuild.
          var generatePackageStepsStep = Jarvis.accessData('JarvisService.Step', 'fetch', {
            filter: Filter.eq('name', 'generatePackageSteps').and().eq('jarvisBuild', step.jarvisBuild.id),
            limit: 1,
          }).objs[0];

          if (!generatePackageStepsStep) {
            var errorMessage =
              'The generatePackageStep Step has not been found. Please integrate it into the Pipeline.';
            Jarvis.visualizedLog(
              Logger.Level.ERROR,
              'Failed to find generatePackageSteps step for build: {}. Cannot register LLM TA step.',
              step.jarvisBuild.id
            );
            Jarvis.visualizedLog(Logger.Level.ERROR, errorMessage);
            return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.ERROR).build();
          }

          var llmTaDryRunPercent;
          var llmTaDryRunConfig = Jarvis.buildConfigValue('llmTaDryRun');
          if (llmTaDryRunConfig) {
            llmTaDryRunPercent = parseFloat(llmTaDryRunConfig) * 100;
          } else {
            llmTaDryRunPercent = 10;
          }
          var llmTaDryRunThreshold = Math.random() * 100;
          var llmTaDryRunFlag = llmTaDryRunThreshold < llmTaDryRunPercent;

          Jarvis.visualizedLog(
            Logger.Level.INFO,
            'LLM TA dry run config: percent={}%, threshold={}%, dryRunFlag={}',
            llmTaDryRunPercent.toFixed(2),
            llmTaDryRunThreshold.toFixed(2),
            llmTaDryRunFlag
          );

          var llmTaDryRunFlagStash = step.jarvisBuild.stashFor('llmTaDryRunFlag');
          llmTaDryRunFlagStash.writeString(JSON.stringify(llmTaDryRunFlag));

          /*
           * The Type Dependency Collector is intentionally not shipped on this support branch. Write
           * the `typeDependencyContext` stash with default sentinel values so the downstream LLM TA
           * step builds `LlmTAFullAnalysisSpec` with valid strings instead of `null`.
           */
          var typeDepsStash = step.jarvisBuild.stashFor('typeDependencyContext');
          typeDepsStash.writeString(
            JSON.stringify({
              typeDependencyMap: 'No type dependency data available for this build.',
              modifiedTypeNames: 'No modified type names extracted for this build.',
            })
          );

          var addLlmTaStep = Jarvis.Step.make({
            id: step.jarvisBuild.id + '--runLlmTestAvoidance',
            name: 'runLlmTestAvoidance',
            input: C3.Map.ofStrToAny(
              'package',
              customPkgName,
              'customPkgName',
              customPkgName,
              'customPkgVersion',
              customPkgVersion
            ),
            next: generatePackageStepsStep.id,
            maxRetries: 3,
          });

          // TODO ENGR-25981 [LLM TA] Use LlmTaJarvis.runStepLogic as main step lambda
          var addLlmTaStepLambda = Jarvis.Lambda.make({
            name: 'runLlmTestAvoidance',
            value: Lambda.fromJsSrc(function (step) {
              return JarvisBaseToolkit.LlmTestAvoidance.runStep(step);
            }),
            buildId: step.jarvisBuild.id,
          });

          Jarvis.addSteps([addLlmTaStep]);
          Jarvis.registerBuildLambdas([addLlmTaStepLambda]);
          Jarvis.visualizedLog(
            Logger.Level.INFO,
            'Registered LLM TA step and lambda for build: {}',
            step.jarvisBuild.id
          );
        } else {
          // Flipping the flag to false if change limits are exceed to avoid making report in `buildSummary.js` step
          Jarvis.visualizedLog(
            Logger.Level.INFO,
            'LLM Test Avoidance not triggered. Setting enableLlmTestAvoidance to false.'
          );
          Jarvis.setBuildConfigValue('enableLlmTestAvoidance', 'false');
        }
      } else {
        Jarvis.visualizedLog(
          Logger.Level.INFO,
          'Test avoidance skipped: branch "{}" does not match regex "{}".',
          step.jarvisBuild.branch,
          testAvoidanceBranchRegex
        );
        testAvoidanceOutputMessage =
          'Test avoidance was not run because branch ' +
          step.jarvisBuild.branch +
          ' did not match regex ' +
          testAvoidanceBranchRegex;

        // Static test avoidance did not run, so LLM Test Avoidance must not run either. Disable it to avoid
        // referencing test avoidance artifacts (e.g. the llmTaResults stash) that were never produced in the
        // `generatePackageSteps` step.
        Jarvis.setBuildConfigValue('enableLlmTestAvoidance', 'false');
      }
    } catch (e) {
      Jarvis.visualizedLog(Logger.Level.ERROR, 'Test avoidance failed with error: {}', e.toString());
      // Queue step to surface instantiation error to the user.
      // eslint-disable-next-line no-redeclare
      var errorMessage =
        'Failed to run test avoidance steps because of the following error. ' +
        'Please reach out to ENG-X immediately.\\n' +
        e.toString();

      var testAvoidanceInstErrorStep = Jarvis.Step.builder()
        .id(step.jarvisBuild.id + '-testAvoidanceInstErrorStep')
        .name('c3standardsStepInstError')
        .input(step.input.with('errorMessage', errorMessage))
        .jarvisBuild(step.jarvisBuild)
        .build();
      Jarvis.addSteps([testAvoidanceInstErrorStep]);
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'Queued Test Avoidance Error Step to surface test avoidance failure to the user.'
      );
    }

    Jarvis.visualizedLog(Logger.Level.INFO, 'Fetching branch group information for build: {}', step.jarvisBuild.id);

    var branch = Jarvis.accessData('JarvisService.Build', 'fetch', {
      filter: Filter.eq('id', step.jarvisBuild.id),
      include: 'serviceBranch.branchGroup.name, serviceBranch.branchGroup.triggerOptions.this',
    }).objs[0];

    if (branch == null) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'No branch group information found for build: {}. Returning ERROR status.',
        step.jarvisBuild.id
      );
      // Unable to find branch information for the current build. Use current build configs without modification.
      Jarvis.visualizedLog(Logger.Level.ERROR, 'No branch group information found for the current build.');
      return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.ERROR).build();
    }

    branch = branch.serviceBranch;

    var branchGroupName = branch.branchGroup.name;
    var branchGroupPreReleaseTag = branch.branchGroup.triggerOptions.preReleaseTag;

    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'Branch group: "{}", preReleaseTag: "{}"',
      branchGroupName,
      branchGroupPreReleaseTag
    );

    // Only set configs for managed branch groups
    var isManagedBranch =
      new RegExp('code analytics \\(managed\\)').test(branchGroupName) &&
      Str.startsWith(branchGroupPreReleaseTag, 'code');

    var buildValidationsOutputMessage = [
      `The Build "${step.jarvisBuild.id}" does not belong to any managed branch groups. No configurations will be modified.\n\n`,
    ];

    if (!isManagedBranch) {
      Jarvis.visualizedLog(
        Logger.Level.INFO,
        'Build does not belong to a managed branch group. No configurations will be modified.'
      );
      // Not a managed branch - let users set their own configs
      Jarvis.visualizedLog(Logger.Level.INFO, '{}', buildValidationsOutputMessage + testAvoidanceOutputMessage);
      return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.SUCCESS).build();
    }

    // For managed branches, enable code analysis and coverage
    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'Managed branch group detected. Enabling code analysis and coverage configs.'
    );
    var configValue = 'true';
    Jarvis.setBuildConfigValue('registerArtifactsUpstream', 'false');

    var buildConfigs = [
      'enableCodeAnalysis',
      'enablePythonCoverage',
      'enableC3UiCoverage',
      'enableJsServerCoverage',
      'reportResultsToCodeAnalytics',
    ];

    _.forEach(buildConfigs, (config) => Jarvis.setBuildConfigValue(config, configValue));

    Jarvis.visualizedLog(Logger.Level.INFO, 'Set build configs to "{}": {}', configValue, JSON.stringify(buildConfigs));

    buildValidationsOutputMessage =
      `The Build "${step.jarvisBuild.id}" from the Managed Branch Group: "${branchGroupName}" has set the following configurations:\n` +
      _.map(buildConfigs, (config) => `- ${config}`).join('\n') +
      `\nto ${configValue}.\n\n`;

    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'setStandardBuildConfigs step completed successfully for build: {}',
      step.jarvisBuild.id
    );

    Jarvis.visualizedLog(Logger.Level.INFO, '{}', buildValidationsOutputMessage + testAvoidanceOutputMessage);

    return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.SUCCESS).build();
  },
};

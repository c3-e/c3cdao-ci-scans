/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

data = {
  name: 'runBuildValidations',
  value: function (step) {
    // Standards Compliance
    function c3standardsrcForRepository(step, restApi) {
      var sha = step.jarvisBuild.sha;
      var c3standardsrc = {};

      try {
        c3standardsrc = JSON.parse(restApi.getFileContent('.c3standardsrc', sha));
      } catch (e) {
        c3standardsrc.error = e.toString();
      }

      return c3standardsrc;
    }

    var restApi = Jarvis.sourceControlRestApi();
    Jarvis.visualizedLog(Logger.Level.INFO, 'Starting build validations for build: {}', step.jarvisBuild.id);
    var standardsRest = GitHubRestApi.make({
      restInst: restApi.restInst,
      repoUrl: 'https://github.com/c3-e/c3standards',
      sourceControlRepoName: 'c3standards',
      orgWithSrcCtrlRepoName: 'c3-e/c3standards',
    });
    var currentStandards = c3standardsrcForRepository(step, restApi);
    var supportBranchName = currentStandards.branchName;

    if (currentStandards.error) {
      Jarvis.visualizedLog(Logger.Level.WARN, 'Failed to parse .c3standardsrc: {}', currentStandards.error);
    } else {
      Jarvis.visualizedLog(Logger.Level.INFO, 'Resolved .c3standardsrc with support branch: {}', supportBranchName);
    }

    //TODO: ENGR-28036 Automatically resolve standards from server.

    // var supportBranchSha = standardsRest.branch(supportBranchName).sha;
    // var commitCheckMessage;

    // if (supportBranchSha.length) {
    //   commitCheckMessage =
    //     supportBranchSha === currentStandards.sha
    //       ? 'c3Standards are up to date!'
    //       : 'Repository c3standards is outdated. Please update to the latest support branch.';
    // } else {
    //   commitCheckMessage = 'No support branch found. Please contact Eng-X.';
    // }

    // Jarvis.visualizedLog(Logger.Level.INFO, 'c3standards compliance check: {}', commitCheckMessage);

    // restApi.restInst.createCommitStatus(
    //   restApi.orgWithSrcCtrlRepoName,
    //   step.jarvisBuild.sha,
    //   'success',
    //   'C3 Standards Compliance',
    //   commitCheckMessage
    // );

    // // Validate that the c3standards branch version matches the server version.
    // var executorVersion = SemanticVersion.make(step.serverVersion).toMajorMinor().toString();
    // var c3standardsVersionMatch = supportBranchName ? supportBranchName.match(/^support\/v(\d+\.\d+)$/) : null;
    // Jarvis.visualizedLog(
    //   Logger.Level.INFO,
    //   'Validating c3standards branch version against executor server version: {}',
    //   executorVersion
    // );
    // if (c3standardsVersionMatch) {
    //   var c3standardsVersion = c3standardsVersionMatch[1];
    //   if (c3standardsVersion !== executorVersion) {
    //     Jarvis.visualizedLog(
    //       Logger.Level.ERROR,
    //       'Version mismatch: executor server is "{}" but c3standards branch "{}" resolves to "{}".',
    //       executorVersion,
    //       supportBranchName,
    //       c3standardsVersion
    //     );
    //     var versionMismatchMessage = [
    //       'c3standards / executor server version mismatch!',
    //       'The executor server is running version ' +
    //         executorVersion +
    //         ', but the repository c3standards branch is ' +
    //         supportBranchName +
    //         ' (version ' +
    //         c3standardsVersion +
    //         ').',
    //       'These versions must match for the build to proceed.',
    //       'Please upgrade c3standards to match the executor server version by running the GitHub Action auto-upgrader workflow.',
    //     ].join('\n');
    //     Jarvis.visualizedLog(Logger.Level.ERROR, versionMismatchMessage);
    //     return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.ERROR).build();
    //   }
    // }

    // Build Validation
    var branchGroupName = Jarvis.accessData('JarvisService.Step', 'fetch', {
      filter: Filter.eq('id', step.id),
      include: 'jarvisBuild.serviceBranch.this, jarvisBuild.serviceBranch.branchGroup.this',
    }).objs[0].jarvisBuild.serviceBranch.branchGroup.name;

    var branchName = step.jarvisBuild.branch;
    var branchGroupTag = step.jarvisBuild.preReleaseTag;

    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'Branch group: "{}", branch: "{}", preReleaseTag: "{}"',
      branchGroupName,
      branchName,
      branchGroupTag
    );
    var branchMap = {
      stable: '^master$',
      rc: '^release$',
      dev: '^develop$',
      hotfix: '^hotfix.*',
      beta: '^epic/.*',
      support: '^support/v[0-9]+\\.[0-9]+$',
    };

    var tag =
      Object.keys(branchMap).find((tag) => {
        return new RegExp(branchMap[tag]).test(branchName);
      }) || 'alpha';

    Jarvis.visualizedLog(Logger.Level.INFO, 'Resolved tag: "{}" for branch: "{}"', tag, branchName);

    if (new RegExp('code analytics \\(managed\\)').test(branchGroupName)) {
      if (tag === 'support') {
        tag = `codesupp`;
      } else {
        tag = `code${tag}`;
      }
    }

    /*
     * Support branches can use either 'support' or 'stable' tags
     * (some teams use 'stable' when they don't cut a 'master' branch)
     */
    var isValidTag = tag === branchGroupTag || (tag === 'support' && branchGroupTag === 'stable');

    if (!isValidTag) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'Invalid preRelease tag: expected "{}" but found "{}".',
        tag,
        branchGroupTag
      );
      var preReleaseTagMessage = `Incorrect PreRelease Tag! Replace '${branchGroupTag}' with '${tag}'`;
      Jarvis.visualizedLog(Logger.Level.ERROR, preReleaseTagMessage);
      result = Jarvis.Step.Result.make({
        step: step,
        status: Jarvis.Step.Status.ERROR,
      });
      return result;
    }

    // Semantic Version Validation
    var pkgDecls = step.input.pkgDecls;
    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'Starting semantic version validation for {} package declarations.',
      pkgDecls.length
    );
    var repositoryPkgNames = pkgDecls
      .map((packageDecl) => {
        return packageDecl.name;
      })
      .toSet();

    /*
     * In multi-repository builds, we should only consider packages that are in the repository for which the build is
     * running. Skip packages that are not in the list of `currentRepositoryPkgs`.
     */
    function getCurrentRepositoryPkgDecls(step, pkgDecls) {
      var reports =
        Jarvis.accessData('JarvisService.Report', 'fetch', {
          filter: Filter.eq('jarvisBuild', step.jarvisBuild.id)
            .and()
            .eq('category', 'Code Analysis')
            .and()
            .eq('subcategory', 'Current Repository Packages'),
          include: 'data',
        }).objs || [];

      /*
       * If no reports were filed for 'Current Repository Packages', no multi-repository builds were run.
       * Return all locally available pkgDecls in that scenario.
       */
      if (!reports.length) {
        return pkgDecls;
      }

      var currentRepositoryPkgs = C3.Set.fromJson(reports[0].data.currentRepoPkgs);
      return _.filter(pkgDecls, (pkgDecl) => {
        return currentRepositoryPkgs.contains(pkgDecl.name);
      });
    }

    var currentRepositoryPkgDecls = getCurrentRepositoryPkgDecls(step, pkgDecls);
    var semanticVersions = _.map(currentRepositoryPkgDecls, 'version');

    function printPackageList(pkgDecls) {
      return _.map(pkgDecls, (pkgDecl) => {
        return '- ' + pkgDecl.name;
      }).join('\\n');
    }

    // Throw an error when packages have a missing semantic version.
    var packagesWithMissingVersion = _.filter(currentRepositoryPkgDecls, (pkgDecl) => {
      return pkgDecl.version == null;
    });
    if (packagesWithMissingVersion.length) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        '{} packages are missing a semantic version.',
        packagesWithMissingVersion.length
      );
      var missingPkgVersionErrorMessage = [
        'The following packages are missing a semantic version declared in their .c3pkg.json file.',
        'Please set the semantic version to same value as other packages in this repository:',
        printPackageList(packagesWithMissingVersion),
      ].join('\\n');
      Jarvis.visualizedLog(Logger.Level.ERROR, missingPkgVersionErrorMessage);
      return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.ERROR).build();
    }

    // Throw an error when packages have different semantic versions.
    var uniqueSemanticVersions = _.uniq(semanticVersions);
    if (uniqueSemanticVersions.length > 1) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'Found {} different semantic versions across packages: {}',
        uniqueSemanticVersions.length,
        JSON.stringify(uniqueSemanticVersions)
      );
      var packagesGroupedByVersion = _.groupBy(currentRepositoryPkgDecls, 'version');
      var printedSemanticVersions = _.map(_.toPairs(packagesGroupedByVersion), (packageVersionGroup) => {
        var semanticVersion = packageVersionGroup[0];
        var versionPkgDecls = packageVersionGroup[1];
        return ['', 'Version ' + semanticVersion, printPackageList(versionPkgDecls)].join('\\n');
      }).join('\\n');

      var uniqSemVerErrorMessage = [
        'All packages in the repository must have the same semantic version.',
        'Please set the semantic version of the following packages to the same version:',
        printedSemanticVersions,
      ].join('\\n');
      Jarvis.visualizedLog(Logger.Level.ERROR, uniqSemVerErrorMessage);
      return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.ERROR).build();
    }

    /*
     * Throw an error when any dependency as defined as "*" instead of a specific version or if the package belongs
     * to the same repository but does not have latest version.
     */
    var repositorySemanticVersion = SemanticVersion.MajorMinor.make(uniqueSemanticVersions[0]).toString();
    var incorrectDependencySemanticVersions = [];
    var incorrectDependencyVersionPatch = [];
    var VERSION_REGEX = /^[0-9]+\.[0-9]+$/;
    _.each(currentRepositoryPkgDecls, (pkgDecl) => {
      var packageName = pkgDecl.name;
      var dependencies = pkgDecl.dependencies ? C3.Map.fromJson(pkgDecl.dependencies) : C3.Map.fromJson({});
      dependencies.each((depVersion, depPackage) => {
        // Prompt users to use a specific version instead of '*' or a range like ^8.4 or >=8.4.0 <8.5.0
        if (!SemanticVersion.isValid(depVersion.trim())) {
          incorrectDependencySemanticVersions.push(
            '- ' + depPackage + ' in ' + packageName + '.c3pkg.json must have specific semantic version'
          );
        }

        if (repositoryPkgNames.contains(depPackage) && depVersion !== repositorySemanticVersion) {
          incorrectDependencySemanticVersions.push(
            '- ' +
              depPackage +
              ' in ' +
              packageName +
              '.c3pkg.json must match the latest version: ' +
              repositorySemanticVersion
          );
        }

        /*
         * Throw an error when a semantic version of a dependency package, independent from its origin,
         * if it does not conform to `major.minor` dependency version requirement.
         */
        if (!VERSION_REGEX.test(depVersion)) {
          incorrectDependencyVersionPatch.push(
            '- Dependency `' + depPackage + '` must specify a `major.minor` version.'
          );
        }
      });
    });

    var result;
    if (incorrectDependencySemanticVersions.length) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'Found {} incorrect dependency semantic versions.',
        incorrectDependencySemanticVersions.length
      );
      var incorrectDepErrorMessage = [
        'Please set the following dependency semantic version of packages:',
        incorrectDependencySemanticVersions.join('\\n'),
      ].join('\\n');
      Jarvis.visualizedLog(Logger.Level.ERROR, incorrectDepErrorMessage);
      result = Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.ERROR).build();
      return result;
    }

    if (incorrectDependencyVersionPatch.length) {
      Jarvis.visualizedLog(
        Logger.Level.ERROR,
        'Found {} dependencies with incorrect major.minor version format.',
        incorrectDependencyVersionPatch.length
      );
      var incorrectDepPatchMessage = [
        "Dependencies on packages outside the current repository shouldn't have a patch version:",
        incorrectDependencyVersionPatch.join('\\n'),
      ].join('\\n');
      Jarvis.visualizedLog(Logger.Level.ERROR, incorrectDepPatchMessage);
      result = Jarvis.Step.Result.make({
        step: step,
        status: Jarvis.Step.Status.ERROR,
      });
      return result;
    }

    Jarvis.visualizedLog(
      Logger.Level.INFO,
      'All build validations passed. Repository semantic version: {}',
      repositorySemanticVersion
    );
    return Jarvis.Step.Result.builder().step(step).status(Jarvis.Step.Status.SUCCESS).build();
  },
};

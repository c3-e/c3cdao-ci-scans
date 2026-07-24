/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

data = {
  name: 'stashMultiRepo',
  value: function (step) {
    /**
     * We only want to run code analysis on packages that exist in the current repository.
     * Store all the pkgs in a Jarvis.Report that will be retrieved in later steps to determine
     * whether code analysis should be run for a particular package.
     */
    function storeCurrentRepositoryPkgs(step) {
      var pkgPaths = JarvisExecutor.SourceControlManager.pkgPaths(step);
      var currentRepoPkgs = pkgPaths.map((pkgPath) => {
        return Pkg.Decl.fromJsonString(C3.File.fromString(pkgPath).readString()).name;
      });
      var currentRepositoryPkgReport = Jarvis.Report.make({
        data: {
          pkgPaths: pkgPaths,
          currentRepoPkgs: currentRepoPkgs,
        },
        category: 'Code Analysis',
        subcategory: 'Current Repository Packages',
      });
      Jarvis.fileReports([currentRepositoryPkgReport]);
    }

    /**
     * Function to check if the provided branch name exists in the provided repository.
     * Emulates the functionality of GitHub.ensureBranchExists. Used in place of the GitHub API because of a
     * bug where the source branch is marked as required.
     *
     * TODO: ENGR-20014 - [stashMultiRepo] Use GitHub.ensureBranchExists in stashMultiRepo
     */
    function ensureBranchExists(restInst, repo, branch) {
      try {
        restInst.reference('c3-e/' + repo, 'refs/heads/' + branch);
        return true;
      } catch (e) {
        return false;
      }
    }

    /**
     * Function to download the downstream repositories based on the values set in the {@link Jarvis.BranchGroupConfig}.
     * Performs the following:
     * - Re-downloads the code for the repository and SHA on which the {@link Jarvis.Build} was triggered.
     * - Loops through and downloads the code for the configured `downstreamRepositories`.
     */
    function downloadDownstreamRepositories(step) {
      // Hashmap to keep track of the repository-branch pairs stashed in this stashMultiRepo step.
      var stashedRepoBranches = {};

      var restApi = Jarvis.sourceControlRestApi();
      var restInst = restApi.restInst;
      var auth = restInst.auth;
      var url = restInst.url;
      var baseDir = JarvisExecutor.Helper.baseDirFor(step);

      var repositoryName = restApi.sourceControlRepoName;
      var jarvisBuildBranch = step.jarvisBuild.branch;

      // Make note of the downloaded repo and ref.
      stashedRepoBranches[repositoryName] = jarvisBuildBranch;

      var downloadRepositoryByRefLambda = Lambda.fromJsSrc((url, auth, baseDir, repo, ref) => {
        var restApi = GitHubRestApi.make({
          restInst: GitHub.make({ auth: auth, url: url }),
          repoUrl: 'https://github.com/c3-e/' + repo,
          sourceControlRepoName: repo,
          sourceControlType: 'github',
          orgWithSrcCtrlRepoName: 'c3-e/' + repo,
        });

        var repoZipPath = baseDir + '/repository.zip';
        restApi.downloadRepository(FileUrl.make(FileUrl.fromString(repoZipPath)), ref).toString();

        var fileUrl = FileUrl.make(FileUrl.fromString(repoZipPath)).toString();
        var repoUnzipPath = fileUrl.replace('repository.zip', 'repository');
        C3.File.fromString(fileUrl).unzip(repoUnzipPath);
      }).partiallyApply({
        url: url,
        auth: auth,
        baseDir: baseDir,
      });

      // Re-download the current repository and store the current repository packages.
      downloadRepositoryByRefLambda.partiallyApply({ repo: repositoryName, ref: jarvisBuildBranch }).call();
      storeCurrentRepositoryPkgs(step);

      // Download the downstream repositories configured by the users.
      var downstreamRepositories = Jarvis.branchGroupConfigValue('downstreamRepositories') || '{}';
      C3.Map.fromJsonString(downstreamRepositories)
        .entries()
        .collect()
        .each((downstreamRepository) => {
          var repo = downstreamRepository.fst;
          var ref = downstreamRepository.snd;

          /*
           * Determine if a branch with the same name as the one for which the Jarvis build was triggered
           * exists in the downstream repositories. If yes, use that branch. Else, use the configured branch.
           */
          var targetRef = ensureBranchExists(restInst, repo, jarvisBuildBranch) ? jarvisBuildBranch : ref;

          // Make note of the downloaded repo and ref.
          stashedRepoBranches[repo] = targetRef;

          downloadRepositoryByRefLambda
            .partiallyApply({
              repo: repo,
              ref: targetRef,
            })
            .call();
        });

      return stashedRepoBranches;
    }

    /**
     * Function to consolidate the downloaded repositories and store the content in the 'repository.zip' stash.
     * Moves all the files from the `downstreamRepositories` and moves them into the `packagesPath/` directory
     * of the repo for which the {@link Jarvis.Build} was triggered.
     *
     * NOTE: This assumes the `packagesPath/` is the same for all repositories for which the build is being run.
     *
     * This allows the `generatePackagesStep` to pick up packages from all repositories for artifact generation.
     */
    function consolidateAndWritePkgsToContent(step) {
      var baseDir = JarvisExecutor.Helper.baseDirFor(step);
      var repoUnzipPath = baseDir + '/repository';
      var fs = JarvisExecutor.Helper.fs();

      /*
       * More all the files from current and downstream repositories into the same folder
       * so that the `generatePackageSteps` step can get the consolidated pkgPaths under the same directory.
       */
      var dirs = fs.listDirsStream(repoUnzipPath, -1, null, 1).collect();
      var destDir = dirs[0];
      dirs.slice(1).each((srcDir) => {
        var srcFiles = fs.listFiles(srcDir).files;
        var destUrls = _.map(srcFiles, (file) => {
          return file.contentLocation.replace(srcDir, destDir);
        });
        FileSystem.moveFilesBatch(srcFiles, destUrls);
      });

      /*
       * The `stashRepo` step stores all the downloaded repository code into the `Jarvis.Content` keyed by
       * name "repository.zip". Replace the content with the unzipped consolidated repositories directory.
       */
      var repoZipPath = baseDir + '/repository.zip';
      var filesToZip = fs
        .listFiles(repoUnzipPath)
        .files.filter((file) => {
          return !file.contentLocation.includes('.zip');
        })
        .map((file) => {
          return C3.File.make(file);
        });
      fs.zipFiles(repoZipPath, filesToZip, repoUnzipPath + '/');

      // Replace the `repository.zip` stash with the consolidated repository.
      var repoStash = step.jarvisBuild.stashFor('repository.zip');
      repoStash.writeStream(C3.File.fromString(repoZipPath).stream());
    }

    function queueGeneratePackagesStep(step) {
      var generatePackageStepsStep = Jarvis.Step.builder()
        .id(Uuid.create())
        .name('generatePackageSteps')
        .next(step.next)
        .jarvisBuild(step.jarvisBuild)
        .build();
      Jarvis.addSteps([generatePackageStepsStep]);
    }

    function constructLogMessage(stashedRepoBranches) {
      var repoBranchPairs = _.map(_.toPairs(stashedRepoBranches), (kv) => {
        var repo = kv[0];
        var branch = kv[1];
        return '- ' + repo + ': ' + branch;
      }).join('\\n');
      var content = [
        'This multi-repository build includes packages from the following `repository: branch` pairs.',
        '',
        repoBranchPairs,
        '',
        'If a branch of the same name as the branch for which this build was triggered exists in a downstream repository, that branch is used for the multi-repository build.',
        '',
      ].join('\\n');
      return content;
    }

    // Step 1: Download the downstream repositories.
    var stashedRepoBranches = downloadDownstreamRepositories(step);
    var logMessage = constructLogMessage(stashedRepoBranches);

    // Step 2: Consolidate packages into a single repository.zip where the generatePackageSteps step can access them.
    consolidateAndWritePkgsToContent(step);

    // Step 3: Queue the generatePackageSteps step.
    queueGeneratePackagesStep(step);

    return Jarvis.Step.Result.builder().step(step).error(logMessage).status(Jarvis.Step.Status.SUCCESS).build();
  },
};

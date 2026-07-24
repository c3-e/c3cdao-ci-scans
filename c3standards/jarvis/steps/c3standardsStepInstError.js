/*
 * Copyright 2009-2026 C3 AI (www.c3.ai). All Rights Reserved.
 * Confidential and Proprietary C3 Materials.
 * This material, including without limitation any software, is the confidential trade secret and proprietary
 * information of C3 and its licensors. Reproduction, use and/or distribution of this material in any form is
 * strictly prohibited except as set forth in a written license agreement with C3 and/or its authorized distributors.
 * This material may be covered by one or more patents or pending patent applications.
 */

data = {
  name: 'c3standardsStepInstError',
  value: function (step) {
    /**
     * This custom step is triggered if there is an error while trying to instantiate the any custom steps shipped
     * through `c3standards`. We add a new step so as to not interrupt the regular flow of the pipeline.
     */
    var errorMessage = step.input.errorMessage;
    return Jarvis.Step.Result.builder()
      .step(step)
      .status(Jarvis.Step.Status.NON_FATAL_ERROR)
      .error(errorMessage)
      .build();
  },
};

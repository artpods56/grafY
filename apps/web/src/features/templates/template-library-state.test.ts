import { describe, expect, it } from "vitest";

import type {
  TemplateLibraryEvent,
  TemplateLibraryState,
  UseTemplateForm,
} from "./template-library-state";
import {
  canRequestCopy,
  initialTemplateLibraryState,
  templateLibraryReducer,
} from "./template-library-state";

const analysis: UseTemplateForm = {
  templateKey: "personal-location:template-analysis",
  sourceLocationId: "personal-location",
  templateId: "template-analysis",
  graphName: "Analysis starter",
  destinationId: "personal-location",
  folderId: "",
};

const map = {
  templateKey: "team-location:template-map",
  sourceLocationId: "team-location",
  templateId: "template-map",
  graphName: "Map review",
  destinationId: "personal-location",
  folderId: "",
};

function run(
  events: readonly TemplateLibraryEvent[],
  start: TemplateLibraryState = {
    ...initialTemplateLibraryState,
    selectedKey: analysis.templateKey,
  },
): TemplateLibraryState {
  return events.reduce(templateLibraryReducer, start);
}

function opened(events: readonly TemplateLibraryEvent[] = []) {
  return run([{ type: "useOpened", form: analysis }, ...events]);
}

function editing(form: UseTemplateForm): TemplateLibraryState {
  return {
    ...initialTemplateLibraryState,
    selectedKey: form.templateKey,
    use: { phase: "editing", form },
  };
}

describe("use form belongs to one template", () => {
  it("opens with the template the preview was showing", () => {
    const state = opened();
    expect(state.use).toEqual({ phase: "editing", form: analysis });
    expect(canRequestCopy(state)).toEqual(analysis);
  });

  it("drops the form when arrow inspection moves to another template", () => {
    const state = opened([
      { type: "selectionMoved", templateKey: map.templateKey },
    ]);
    expect(state.use.phase).toBe("closed");
    expect(state.selectedKey).toBe(map.templateKey);
  });

  it("keeps the form when inspection stays on the same template", () => {
    const state = opened([
      { type: "selectionMoved", templateKey: analysis.templateKey },
    ]);
    expect(state.use).toEqual({ phase: "editing", form: analysis });
  });

  it("drops the form when a result row is chosen", () => {
    expect(
      opened([{ type: "resultChosen", templateKey: map.templateKey }]).use
        .phase,
    ).toBe("closed");
  });

  it("drops the form when the result set changes", () => {
    const state = opened([{ type: "queryChanged", query: "map" }]);
    expect(state.query).toBe("map");
    expect(state.use.phase).toBe("closed");
  });

  it("ignores field edits once the form is dismissed", () => {
    const state = opened([
      { type: "useDismissed" },
      { type: "graphNameChanged", value: "Typed after close" },
    ]);
    expect(state.use.phase).toBe("closed");
  });

  it("reopens from the template instead of the abandoned draft", () => {
    const state = run([
      { type: "useOpened", form: map },
      { type: "graphNameChanged", value: "Half-typed" },
      {
        type: "createFailed",
        templateKey: analysis.templateKey,
        error: "ignored while editing",
      },
      { type: "useDismissed" },
      { type: "useOpened", form: analysis },
    ]);
    expect(state.use).toEqual({ phase: "editing", form: analysis });
    expect(state.pendingCopy).toEqual([]);
  });
});

describe("copy request phases", () => {
  it("refuses a second request while one is in flight", () => {
    const state = opened([
      { type: "createRequested", templateKey: analysis.templateKey },
    ]);
    expect(state.use.phase).toBe("creating");
    expect(state.pendingCopy).toEqual([analysis.templateKey]);
    expect(canRequestCopy(state)).toBeNull();
    expect(
      run(
        [{ type: "createRequested", templateKey: analysis.templateKey }],
        state,
      ),
    ).toBe(state);
    expect(
      run([{ type: "createRequested", templateKey: map.templateKey }], state),
    ).toBe(state);
    expect(run([{ type: "useOpened", form: map }], state).use.phase).toBe(
      "creating",
    );
  });

  it("keeps a reopened form busy while its template's request is running", () => {
    // The person leaves a running copy, inspects another template, comes back,
    // and opens the form again. The new form is a different request's form, not
    // an idle one, because this template already has a copy in flight.
    const state = opened([
      { type: "createRequested", templateKey: analysis.templateKey },
      { type: "resultChosen", templateKey: map.templateKey },
      { type: "resultChosen", templateKey: analysis.templateKey },
      { type: "useOpened", form: analysis },
    ]);
    expect(state.use).toEqual({ phase: "editing", form: analysis });
    expect(state.pendingCopy).toEqual([analysis.templateKey]);
    expect(canRequestCopy(state)).toBeNull();
    expect(
      run(
        [{ type: "createRequested", templateKey: analysis.templateKey }],
        state,
      ),
    ).toBe(state);
  });

  it("refuses a request when the form cannot produce one", () => {
    const blank = { ...analysis, graphName: "   " };
    expect(canRequestCopy(editing(blank))).toBeNull();
    expect(
      canRequestCopy(editing({ ...analysis, destinationId: "" })),
    ).toBeNull();
  });

  it("keeps the typed form and reports the failure for a retry", () => {
    const state = opened([
      { type: "graphNameChanged", value: "Quarterly copy" },
      { type: "createRequested", templateKey: analysis.templateKey },
      {
        type: "createFailed",
        templateKey: analysis.templateKey,
        error: "The graph could not be created.",
      },
    ]);
    expect(state.use).toEqual({
      phase: "failed",
      form: { ...analysis, graphName: "Quarterly copy" },
      error: "The graph could not be created.",
    });
    expect(state.pendingCopy).toEqual([]);
    expect(canRequestCopy(state)).toEqual({
      ...analysis,
      graphName: "Quarterly copy",
    });
  });

  it("returns the form to editing after a copy is created", () => {
    const state = opened([
      { type: "createRequested", templateKey: analysis.templateKey },
      { type: "createSucceeded", templateKey: analysis.templateKey },
    ]);
    expect(state.use).toEqual({ phase: "editing", form: analysis });
    expect(state.pendingCopy).toEqual([]);
  });

  it("answers only the template the request was addressed to", () => {
    // The copy of `analysis` is abandoned mid-flight and a copy of `map` starts.
    const state = opened([
      { type: "createRequested", templateKey: analysis.templateKey },
      { type: "queryChanged", query: "map" },
      { type: "useOpened", form: map },
      { type: "createRequested", templateKey: map.templateKey },
      {
        type: "createFailed",
        templateKey: analysis.templateKey,
        error: "The old request gave up.",
      },
    ]);
    expect(state.use).toEqual({ phase: "creating", form: map });
    // The abandoned template's copy has answered; the running one has not.
    expect(state.pendingCopy).toEqual([map.templateKey]);
    expect(
      run(
        [
          {
            type: "createFailed",
            templateKey: map.templateKey,
            error: "The graph could not be created.",
          },
        ],
        state,
      ),
    ).toEqual({
      ...state,
      pendingCopy: [],
      use: {
        phase: "failed",
        form: map,
        error: "The graph could not be created.",
      },
    });
  });

  it("ignores a late answer for a form the person already left", () => {
    const closed = opened([
      { type: "createRequested", templateKey: analysis.templateKey },
      { type: "queryChanged", query: "map" },
    ]);
    expect(closed.pendingCopy).toEqual([analysis.templateKey]);
    expect(
      run(
        [
          {
            type: "createFailed",
            templateKey: analysis.templateKey,
            error: "The graph could not be created.",
          },
        ],
        closed,
      ),
    ).toEqual({ ...closed, pendingCopy: [], use: { phase: "closed" } });
    expect(
      run(
        [{ type: "createSucceeded", templateKey: analysis.templateKey }],
        closed,
      ),
    ).toEqual({ ...closed, pendingCopy: [], use: { phase: "closed" } });
  });
});

describe("destination and folder choices", () => {
  it("keeps a folder chosen under the current save location", () => {
    const state = opened([
      { type: "destinationChanged", destinationId: "team-location" },
      { type: "folderChanged", folderId: "folder-fieldwork" },
    ]);
    expect(state.use.phase === "closed").toBe(false);
    if (state.use.phase !== "closed") {
      expect(state.use.form).toEqual({
        ...analysis,
        destinationId: "team-location",
        folderId: "folder-fieldwork",
      });
    }
  });

  it("clears the folder when the save location moves", () => {
    const state = opened([
      { type: "folderChanged", folderId: "folder-fieldwork" },
      { type: "destinationChanged", destinationId: "team-location" },
    ]);
    if (state.use.phase === "closed") throw new Error("form should stay open");
    expect(state.use.form).toEqual({
      ...analysis,
      destinationId: "team-location",
      folderId: "",
    });
  });
});

describe("archive request phases", () => {
  it("refuses a second archive while one runs, whoever it targets", () => {
    const state = run([
      { type: "archiveRequested", templateKey: analysis.templateKey },
    ]);
    expect(state.archive).toEqual({
      phase: "archiving",
      templateKey: analysis.templateKey,
    });
    expect(
      run(
        [{ type: "archiveRequested", templateKey: analysis.templateKey }],
        state,
      ),
    ).toBe(state);
    expect(
      run([{ type: "archiveRequested", templateKey: map.templateKey }], state),
    ).toBe(state);
  });

  it("closes the archived template's form but not another one", () => {
    const archivedOwn = run(
      [
        { type: "useOpened", form: analysis },
        { type: "archiveRequested", templateKey: analysis.templateKey },
        { type: "archiveSucceeded", templateKey: analysis.templateKey },
      ],
      { ...initialTemplateLibraryState, selectedKey: analysis.templateKey },
    );
    expect(archivedOwn.use.phase).toBe("closed");
    expect(archivedOwn.archive.phase).toBe("idle");

    const otherForm = run(
      [
        { type: "useOpened", form: map },
        { type: "archiveRequested", templateKey: analysis.templateKey },
        { type: "archiveSucceeded", templateKey: analysis.templateKey },
      ],
      { ...initialTemplateLibraryState, selectedKey: analysis.templateKey },
    );
    expect(otherForm.use.phase).toBe("editing");
  });

  it("keeps an archive failure attached to the template it happened to", () => {
    const state = run([
      { type: "archiveRequested", templateKey: analysis.templateKey },
      { type: "archiveFailed", templateKey: analysis.templateKey, error: "no" },
    ]);
    expect(state.archive).toEqual({
      phase: "failed",
      templateKey: analysis.templateKey,
      error: "no",
    });
    expect(
      run(
        [
          {
            type: "archiveFailed",
            templateKey: map.templateKey,
            error: "late",
          },
        ],
        state,
      ),
    ).toBe(state);
  });
});

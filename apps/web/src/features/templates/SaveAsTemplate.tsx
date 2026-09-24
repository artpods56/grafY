"use client";

import * as React from "react";
import { ArrowLeft, FileStack, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLoader } from "@/components/brand";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { workbenchGraphPath } from "@/features/workbench/routes";
import { WorkspaceRail } from "@/features/workspaces/WorkspaceLayout";
import { useSavedGraphs, useWorkspaces } from "@/hooks/use-api";
import { FINE_POINTER_QUERY } from "@/hooks/use-media-query";
import { createWorkspaceTemplate } from "@/lib/api";
import {
  templateLocationLabel,
  templateUseErrorMessage,
} from "./TemplateLibrary";

export interface SaveAsTemplateSource {
  workspaceId: string;
  graphId: string;
  revision: number;
}

export function SaveAsTemplate({
  source,
}: {
  source: SaveAsTemplateSource | null;
}) {
  const sourceKey = source
    ? JSON.stringify([source.workspaceId, source.graphId, source.revision])
    : "missing-source";

  return <SaveAsTemplateFlow key={sourceKey} source={source} />;
}

function SaveAsTemplateFlow({
  source,
}: {
  source: SaveAsTemplateSource | null;
}) {
  const router = useRouter();
  const { session, logout } = useAuthSession();
  const { data: workspaces } = useWorkspaces(session.user_id);
  const location = workspaces?.find(
    (workspace) => workspace.id === source?.workspaceId,
  );
  const {
    data: graphList,
    error,
    isLoading,
    mutate,
  } = useSavedGraphs(source?.workspaceId);
  const graph = graphList?.graphs.find((item) => item.id === source?.graphId);
  const [nameOverride, setNameOverride] = React.useState<string | null>(null);
  const [description, setDescription] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const nameInputRef = React.useRef<HTMLInputElement>(null);
  const autoFocusAttemptedRef = React.useRef(false);

  const name = nameOverride ?? graph?.name ?? "";

  React.useEffect(() => {
    if (
      autoFocusAttemptedRef.current ||
      !source ||
      !graph ||
      !location?.capabilities.includes("create_template")
    ) {
      return;
    }
    autoFocusAttemptedRef.current = true;
    if (
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(FINE_POINTER_QUERY).matches
    ) {
      nameInputRef.current?.focus();
    }
  }, [graph, location, source]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!source || !graph || !location || !name.trim()) return;
    setBusy(true);
    setMessage(null);
    try {
      const created = await createWorkspaceTemplate(location.id, {
        source_graph_id: source.graphId,
        source_revision: source.revision,
        name: name.trim(),
        description: description.trim() || null,
      });
      router.push(`/templates?created=${encodeURIComponent(created.id)}`);
    } catch (caught) {
      setMessage(templateUseErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const sourceHref =
    location && source
      ? workbenchGraphPath(location.slug, source.graphId)
      : "/";

  return (
    <div className="grafy-template-page">
      {workspaces ? (
        <WorkspaceRail
          workspaces={workspaces}
          session={session}
          onLogout={logout}
        />
      ) : null}
      <main className="grafy-save-template">
        <Link className="grafy-save-template__back" href={sourceHref}>
          <ArrowLeft size={14} aria-hidden="true" /> Back to graph
        </Link>
        <header>
          <span className="grafy-save-template__mark">
            <FileStack size={20} aria-hidden="true" />
          </span>
          <p className="grafy-template-library__eyebrow">
            Graph / Save as template
          </p>
          <h1>Save as template</h1>
          <p>
            Capture one exact revision as a reusable starting point. Graphs
            created from it are independent copies.
          </p>
        </header>

        {!source ? (
          <section className="grafy-template-state" role="alert">
            <h2>Source graph is missing</h2>
            <p>
              Open Save as template from a graph so its exact revision is known.
            </p>
            <Link className="grafy-workspace-button" href="/">
              Go to My graphs
            </Link>
          </section>
        ) : isLoading || !workspaces ? (
          <section className="grafy-template-state" aria-live="polite">
            <BrandLoader size={34} label="Loading graph" />
            <p>Loading the source revision…</p>
          </section>
        ) : error ? (
          <section className="grafy-template-state" role="alert">
            <h2>Graph could not be loaded</h2>
            <p>Check the connection and retry.</p>
            <button
              type="button"
              className="grafy-workspace-button"
              onClick={() => void mutate()}
            >
              Retry
            </button>
          </section>
        ) : !location || !graph ? (
          <section className="grafy-template-state" role="alert">
            <h2>Graph is no longer available</h2>
            <p>Return to My graphs and choose another source.</p>
          </section>
        ) : !location.capabilities.includes("create_template") ? (
          <section className="grafy-template-state" role="alert">
            <h2>Template permission required</h2>
            <p>
              You can view this graph, but cannot save templates in this
              location.
            </p>
          </section>
        ) : (
          <form className="grafy-save-template__form" onSubmit={submit}>
            <div className="grafy-save-template__source">
              <span>Source</span>
              <strong>{graph.name}</strong>
              <small>
                revision {source.revision} · {templateLocationLabel(location)}
              </small>
            </div>
            <label>
              Template name
              <input
                ref={nameInputRef}
                value={name}
                onChange={(event) => setNameOverride(event.target.value)}
                maxLength={160}
                required
              />
            </label>
            <label>
              Description <span>optional</span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={1000}
                rows={4}
                placeholder="What is this a useful starting point for?"
              />
            </label>
            {message ? (
              <p className="grafy-template-use__error" role="alert">
                {message}
              </p>
            ) : null}
            <div className="grafy-save-template__actions">
              <Link className="grafy-workspace-button" href={sourceHref}>
                Cancel
              </Link>
              <button
                type="submit"
                className="grafy-workspace-button grafy-workspace-button--primary"
                disabled={busy || !name.trim()}
              >
                {busy ? (
                  <LoaderCircle className="grafy-template-spin" size={14} />
                ) : null}
                {busy ? "Saving…" : message ? "Try again" : "Save template"}
              </button>
            </div>
          </form>
        )}
      </main>
    </div>
  );
}

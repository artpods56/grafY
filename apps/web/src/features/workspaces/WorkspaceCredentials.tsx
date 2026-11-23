"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  KeyRound,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Trash2,
  User,
  Users,
  Vault,
} from "lucide-react";
import useSWR from "swr";

import { Button, IconButton } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import {
  CredentialBadge,
  CredentialCallout,
  VerificationBadge,
} from "@/features/credentials/CredentialBadge";
import {
  CredentialForm,
  type CredentialProvider,
} from "@/features/credentials/CredentialForm";
import {
  credentialStatusLabel,
  credentialStatusTone,
  providerDisplayName,
} from "@/features/credentials/credential-display";
import {
  credentialListReducer,
  type CredentialListState,
} from "@/features/credentials/credential-list-state";
import { useNodeRegistry } from "@/hooks/use-api";
import {
  deleteCredential,
  listCredentials,
  reverifyCredential,
  updateCredential,
  type Credential,
  type CredentialLocation,
  type CredentialScope,
} from "@/lib/api";
import { credentialVerificationFailure } from "@/lib/api/credentials";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { workspaceSettingsStyles as settings } from "./workspace-settings.styles";

const spin = stylex.keyframes({
  from: { transform: "rotate(0deg)" },
  to: { transform: "rotate(360deg)" },
});

const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, monospace";

const styles = stylex.create({
  lists: { display: "grid", gap: "28px", marginTop: "22px" },
  list: { display: "grid", gap: "12px" },
  listHeading: {
    display: "flex",
    alignItems: "start",
    gap: "10px",
  },
  listIcon: {
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    width: "28px",
    height: "28px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
  },
  listTitle: {
    margin: 0,
    display: "flex",
    alignItems: "center",
    gap: "8px",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 560,
  },
  count: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    fontVariantNumeric: "tabular-nums",
  },
  listSubtitle: {
    margin: "3px 0 0",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  rows: {
    display: "grid",
    margin: 0,
    padding: 0,
    listStyle: "none",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: tokens.radiusLg,
    overflow: "hidden",
  },
  row: {
    display: "grid",
    gap: "10px",
    padding: "12px 14px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: {
      default: tokens.colorDivider,
      ":first-child": "transparent",
    },
    backgroundColor: tokens.colorBg,
  },
  rowMain: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: "10px 16px",
  },
  description: {
    minWidth: 0,
    flexGrow: 1,
    flexBasis: "240px",
    display: "grid",
    gap: "5px",
  },
  identity: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "6px 8px",
  },
  label: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 550,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  hint: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: tokens.fontSizeXs,
    letterSpacing: "0.02em",
  },
  status: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "4px 8px",
  },
  meta: {
    minWidth: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  actions: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  confirm: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "6px",
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  edit: {
    display: "grid",
    gap: "10px",
    padding: "12px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurface,
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
  editFields: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(0, 1fr)",
      "@media (min-width: 720px)": "repeat(2, minmax(0, 1fr))",
    },
    gap: "10px 12px",
  },
  editActions: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "6px",
  },
  empty: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    margin: 0,
    padding: "14px 16px",
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  muted: { margin: 0, color: tokens.colorSubtle, fontSize: tokens.fontSizeSm },
  spinner: {
    animationName: spin,
    animationDuration: {
      default: "900ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

const LIST_COPY: Record<
  CredentialScope,
  { title: string; subtitle: string; empty: string }
> = {
  personal: {
    title: "Personal credentials",
    subtitle: "Only you can use these keys across any workspace.",
    empty:
      "No personal keys yet. Add one to run provider nodes on your own account.",
  },
  shared: {
    title: "Shared workspace credentials",
    subtitle:
      "Shared with members who can run graphs in this workspace. Owners manage these keys.",
    empty: "No shared keys yet.",
  },
};

function Spinner({ size }: { size: number }) {
  return (
    <LoaderCircle
      size={size}
      aria-hidden="true"
      {...stylex.props(styles.spinner)}
    />
  );
}

function EditCredentialForm({
  row,
  state,
  dispatch,
}: {
  row: Credential;
  state: CredentialListState;
  dispatch: (action: Parameters<typeof credentialListReducer>[1]) => void;
}) {
  const saving = state.kind === "busy" && state.operation === "update";
  const failure = state.kind === "editing" ? state.failure : undefined;
  return (
    <form
      aria-label={`Edit ${row.label}`}
      {...stylex.props(styles.edit)}
      onSubmit={(event) => {
        event.preventDefault();
        if (saving) return;
        const data = new FormData(event.currentTarget);
        const label = String(data.get("label") ?? "").trim();
        const value = String(data.get("value") ?? "");
        const renamed = label && label !== row.label ? label : null;
        if (!renamed && !value) {
          dispatch({ kind: "cancel" });
          return;
        }
        const save_if_unverified =
          event.nativeEvent instanceof SubmitEvent &&
          event.nativeEvent.submitter?.getAttribute("value") === "save-anyway";
        dispatch({
          kind: "submit-edit",
          id: row.id,
          body: {
            label: renamed,
            value: value || null,
            verify: true,
            save_if_unverified,
          },
        });
      }}
    >
      <div {...stylex.props(styles.editFields)}>
        <Field label="Label">
          <TextInput
            name="label"
            defaultValue={row.label}
            maxLength={160}
            disabled={saving}
            required
          />
        </Field>
        <Field
          label="Replacement key"
          description="Leave empty to keep the current key."
        >
          <TextInput
            name="value"
            type="password"
            mono
            placeholder="Paste a new key to rotate"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            disabled={saving}
          />
        </Field>
      </div>
      {failure && (
        <CredentialCallout
          tone={failure.canSave ? "warning" : "danger"}
          title={failure.canSave ? "Not verified" : "Not saved"}
        >
          {failure.message}
        </CredentialCallout>
      )}
      <div {...stylex.props(styles.editActions)}>
        <Button type="submit" size="xs" variant="primary" disabled={saving}>
          {saving ? <Spinner size={12} /> : null}
          {saving ? "Saving…" : "Save changes"}
        </Button>
        {failure?.canSave && (
          <Button
            type="submit"
            value="save-anyway"
            size="xs"
            variant="secondary"
            disabled={saving}
          >
            Save anyway
          </Button>
        )}
        <Button
          type="button"
          size="xs"
          variant="ghost"
          disabled={saving}
          onClick={() => dispatch({ kind: "cancel" })}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

function CredentialRow({
  row,
  canManage,
  state,
  dispatch,
}: {
  row: Credential;
  canManage: boolean;
  state: CredentialListState;
  dispatch: (action: Parameters<typeof credentialListReducer>[1]) => void;
}) {
  const busy = state.kind === "busy";
  const mine = "id" in state && state.id === row.id;
  const verifying = busy && mine && state.operation === "verify";
  const deleting = busy && mine && state.operation === "delete";
  const confirming = state.kind === "confirming-delete" && mine;
  const editing =
    mine &&
    (state.kind === "editing" || (busy && state.operation === "update"));
  const notice =
    state.kind === "idle" && state.notice?.id === row.id
      ? state.notice
      : undefined;
  const detail = [row.verification_hint, row.verification_message]
    .filter(Boolean)
    .join(" · ");

  return (
    <li data-credential-row={row.id} {...stylex.props(styles.row)}>
      <div {...stylex.props(styles.rowMain)}>
        <div {...stylex.props(styles.description)}>
          <div {...stylex.props(styles.identity)}>
            <strong title={row.label} {...stylex.props(styles.label)}>
              {row.label}
            </strong>
            <CredentialBadge tone="outline">
              {providerDisplayName(row.provider_kind)}
            </CredentialBadge>
            {row.key_hint && (
              <code {...stylex.props(styles.hint)}>{row.key_hint}</code>
            )}
          </div>
          <div {...stylex.props(styles.status)}>
            {row.usable ? (
              <VerificationBadge status={row.verification_status} />
            ) : (
              <CredentialBadge
                tone="danger"
                title="This key cannot be decrypted with the server's current keys."
              >
                Unavailable
              </CredentialBadge>
            )}
            {detail && <span {...stylex.props(styles.meta)}>{detail}</span>}
          </div>
        </div>
        {canManage &&
          (confirming || deleting ? (
            <div
              role="group"
              aria-label={`Delete ${row.label}?`}
              {...stylex.props(styles.confirm)}
            >
              <span>Delete this key?</span>
              <Button
                type="button"
                size="xs"
                variant="danger"
                disabled={deleting}
                onClick={() => dispatch({ kind: "confirm-delete", id: row.id })}
              >
                {deleting ? <Spinner size={12} /> : null}
                {deleting ? "Deleting…" : "Confirm delete"}
              </Button>
              <Button
                type="button"
                size="xs"
                variant="ghost"
                disabled={deleting}
                onClick={() => dispatch({ kind: "cancel" })}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <div {...stylex.props(styles.actions)}>
              <IconButton
                label={`Re-verify ${row.label}`}
                title={
                  row.supports_verification
                    ? "Re-verify with the provider"
                    : "This provider cannot check keys"
                }
                size="sm"
                variant="ghost"
                disabled={busy || !row.usable || !row.supports_verification}
                onClick={() => dispatch({ kind: "verify", id: row.id })}
              >
                {verifying ? (
                  <Spinner size={14} />
                ) : (
                  <RefreshCw size={14} aria-hidden="true" />
                )}
              </IconButton>
              <IconButton
                label={`Edit ${row.label}`}
                title="Rename or rotate the key"
                size="sm"
                variant="ghost"
                disabled={busy || editing}
                onClick={() => dispatch({ kind: "edit", id: row.id })}
              >
                <Pencil size={14} aria-hidden="true" />
              </IconButton>
              <IconButton
                label={`Delete ${row.label}`}
                title="Delete key"
                size="sm"
                variant="danger"
                disabled={busy}
                onClick={() => dispatch({ kind: "ask-delete", id: row.id })}
              >
                <Trash2 size={14} aria-hidden="true" />
              </IconButton>
            </div>
          ))}
      </div>
      {editing && (
        <EditCredentialForm row={row} state={state} dispatch={dispatch} />
      )}
      {notice && (
        <CredentialCallout
          tone={notice.tone}
          title={notice.tone === "danger" ? "Failed" : "Done"}
        >
          {notice.message}
        </CredentialCallout>
      )}
    </li>
  );
}

function CredentialList({
  workspaceId,
  scope,
  canManage,
  providers,
}: {
  workspaceId: string;
  scope: CredentialScope;
  canManage: boolean;
  providers: readonly CredentialProvider[];
}) {
  const location: CredentialLocation =
    scope === "shared" ? { scope, workspaceId } : { scope };
  const { data, error, isLoading, mutate } = useSWR(
    ["provider-credentials", scope, workspaceId],
    () => listCredentials(location),
  );
  const [state, dispatch] = useEffectReducer(
    credentialListReducer,
    { kind: "idle" },
    (effect, dispatch) => {
      const fail = (cause: unknown) =>
        dispatch({
          kind: "failed",
          id: effect.id,
          ...credentialVerificationFailure(cause),
        });
      if (effect.kind === "delete") {
        void deleteCredential(location, effect.id)
          .then(() => mutate())
          .then(
            () => dispatch({ kind: "done", id: effect.id, tone: "neutral" }),
            fail,
          );
        return;
      }
      const request =
        effect.kind === "verify"
          ? reverifyCredential(location, effect.id)
          : updateCredential(location, effect.id, effect.body);
      const rotated = effect.kind === "verify" || effect.body.value != null;
      void request.then(async (updated) => {
        await mutate();
        dispatch({
          kind: "done",
          id: effect.id,
          tone: rotated
            ? credentialStatusTone(updated.verification_status)
            : "success",
          message: rotated
            ? (updated.verification_message ??
              credentialStatusLabel[updated.verification_status])
            : `Renamed to “${updated.label}”.`,
        });
      }, fail);
    },
    { flush: "sync" },
  );
  const copy = LIST_COPY[scope];
  const Icon = scope === "personal" ? User : Users;
  const headingId = `credentials-${scope}-heading`;

  return (
    <section aria-labelledby={headingId} {...stylex.props(styles.list)}>
      <div {...stylex.props(styles.listHeading)}>
        <span aria-hidden="true" {...stylex.props(styles.listIcon)}>
          <Icon size={15} />
        </span>
        <div>
          <h3 id={headingId} {...stylex.props(styles.listTitle)}>
            {copy.title}
            {data && data.length > 0 && (
              <span {...stylex.props(styles.count)}>{data.length}</span>
            )}
          </h3>
          <p {...stylex.props(styles.listSubtitle)}>{copy.subtitle}</p>
        </div>
      </div>
      {isLoading ? (
        <p role="status" {...stylex.props(styles.muted)}>
          Loading credentials…
        </p>
      ) : error ? (
        <Notice
          tone="danger"
          action={
            <Button variant="secondary" size="xs" onClick={() => void mutate()}>
              Retry
            </Button>
          }
        >
          Credentials could not be loaded.
        </Notice>
      ) : data && data.length > 0 ? (
        <ul {...stylex.props(styles.rows)}>
          {data.map((row) => (
            <CredentialRow
              key={row.id}
              row={row}
              canManage={canManage}
              state={state}
              dispatch={dispatch}
            />
          ))}
        </ul>
      ) : (
        <p {...stylex.props(styles.empty)}>
          <KeyRound size={15} aria-hidden="true" />
          <span>
            {copy.empty}
            {!canManage && scope === "shared"
              ? " Workspace owners can add them here."
              : ""}
          </span>
        </p>
      )}
      {canManage && (
        <CredentialForm
          workspaceId={workspaceId}
          providers={providers}
          scopes={[scope]}
          onSaved={() => mutate()}
        />
      )}
    </section>
  );
}

export function WorkspaceCredentials({
  workspaceId,
  canManageShared,
  canViewShared,
}: {
  workspaceId: string;
  canManageShared: boolean;
  canViewShared: boolean;
}) {
  const { data: registry } = useNodeRegistry(workspaceId);
  const byKind = new Map<string, CredentialProvider>();
  for (const node of registry?.nodes ?? []) {
    for (const input of node.secret_inputs ?? []) {
      const known = byKind.get(input.provider_kind);
      const fields = new Set([
        ...(known?.fields ?? []),
        ...input.config_dependencies,
      ]);
      byKind.set(input.provider_kind, {
        kind: input.provider_kind,
        fields: [...fields],
        supportsVerification:
          (known?.supportsVerification ?? false) || input.supports_verification,
      });
    }
  }
  const providers = [...byKind.values()].sort((left, right) =>
    providerDisplayName(left.kind).localeCompare(
      providerDisplayName(right.kind),
    ),
  );
  return (
    <section
      {...stylex.props(settings.section)}
      aria-labelledby="workspace-credentials-heading"
    >
      <div {...stylex.props(settings.sectionHeading)}>
        <div>
          <h2
            id="workspace-credentials-heading"
            {...stylex.props(settings.headingTitle)}
          >
            Provider credentials
          </h2>
          <p {...stylex.props(settings.headingText)}>
            Keys that nodes use to call model and document providers. A saved
            key is never shown again, only its last characters.
          </p>
        </div>
        <Vault
          size={18}
          aria-hidden="true"
          {...stylex.props(settings.headingIcon)}
        />
      </div>
      <div {...stylex.props(styles.lists)}>
        <CredentialList
          workspaceId={workspaceId}
          providers={providers}
          scope="personal"
          canManage
        />
        {canViewShared && (
          <CredentialList
            workspaceId={workspaceId}
            providers={providers}
            scope="shared"
            canManage={canManageShared}
          />
        )}
      </div>
    </section>
  );
}

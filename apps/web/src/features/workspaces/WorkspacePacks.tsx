"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Blocks } from "lucide-react";
import useSWR, { useSWRConfig } from "swr";
import useSWRMutation from "swr/mutation";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Switch } from "@/components/ui/switch";
import { workspaceNodeRegistryKey } from "@/hooks/use-api";
import {
  listWorkspacePacks,
  setWorkspacePack,
  workspacePacksPath,
  type CatalogPack,
  type NodeRegistry,
  type Workspace,
} from "@/lib/api";
import { request } from "@/lib/api/client";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { workspaceSettingsStyles as settings } from "./workspace-settings.styles";

export function WorkspacePacks({ workspace }: { workspace: Workspace }) {
  const key = workspacePacksPath(workspace.id);
  const canManage = workspace.capabilities.includes("manage_packs");
  const {
    data: packs,
    error,
    mutate: reloadPacks,
  } = useSWR(key, () => listWorkspacePacks(workspace.id));
  const { mutate } = useSWRConfig();
  const {
    trigger,
    isMutating,
    error: updateError,
  } = useSWRMutation(
    key,
    async (_, { arg }: { arg: { slug: string; subscribed: boolean } }) => {
      const pack = await setWorkspacePack(workspace.id, arg.slug, {
        subscribed: arg.subscribed,
      });
      const registryKey = workspaceNodeRegistryKey(workspace.id);
      // Fetch even when the workbench is unmounted on the Settings route.
      await mutate(
        registryKey,
        () => request<NodeRegistry>("GET", registryKey),
        {
          revalidate: false,
        },
      ).catch(() => mutate(registryKey, undefined));
      return pack;
    },
  );

  return (
    <section
      id="tool-packs"
      {...stylex.props(settings.section)}
      aria-labelledby="tool-packs-heading"
    >
      <div {...stylex.props(settings.sectionHeading)}>
        <div>
          <h2 id="tool-packs-heading" {...stylex.props(settings.headingTitle)}>
            Tool packs
          </h2>
          <p {...stylex.props(settings.headingText)}>
            Choose which steps appear in this Workspace’s picker.
          </p>
        </div>
        <Blocks
          size={18}
          aria-hidden="true"
          {...stylex.props(settings.headingIcon)}
        />
      </div>
      {error ? (
        <Notice
          tone="danger"
          xstyle={settings.tokenMessage}
          action={
            <Button
              variant="secondary"
              size="xs"
              onClick={() => void reloadPacks()}
            >
              Retry
            </Button>
          }
        >
          Tool packs could not be loaded.
        </Notice>
      ) : null}
      {updateError ? (
        <Notice tone="danger" xstyle={settings.tokenMessage}>
          The pack subscription could not be changed.
        </Notice>
      ) : null}
      {packs ? (
        packs.length > 0 ? (
          <ul {...stylex.props(s.list)}>
            {packs.map((pack) => (
              <PackRow
                key={pack.slug}
                pack={pack}
                disabled={!canManage || isMutating}
                onChange={(subscribed) => {
                  void trigger(
                    { slug: pack.slug, subscribed },
                    {
                      populateCache: (
                        updated,
                        current: readonly CatalogPack[] | undefined,
                      ) =>
                        current?.map((entry) =>
                          entry.slug === updated.slug ? updated : entry,
                        ) ?? [updated],
                      revalidate: true,
                      throwOnError: false,
                    },
                  );
                }}
              />
            ))}
          </ul>
        ) : (
          <p {...stylex.props(s.muted)}>No optional tool packs available.</p>
        )
      ) : !error ? (
        <p role="status" {...stylex.props(s.muted)}>
          Loading tool packs…
        </p>
      ) : null}
    </section>
  );
}

function PackRow({
  pack,
  disabled,
  onChange,
}: {
  pack: CatalogPack;
  disabled: boolean;
  onChange: (subscribed: boolean) => void;
}) {
  const labelId = React.useId();
  return (
    <li {...stylex.props(s.row)}>
      <div {...stylex.props(s.copy)}>
        <div {...stylex.props(s.title)}>
          <strong id={labelId} {...stylex.props(s.titleText)}>
            {pack.title}
          </strong>
          {pack.always_on ? (
            <span {...stylex.props(s.badge)}>Always on</span>
          ) : null}
        </div>
        <p {...stylex.props(s.muted)}>{pack.description}</p>
        <p {...stylex.props(s.meta)}>
          {pack.operator_count} {pack.operator_count === 1 ? "step" : "steps"}
          {pack.provider_count
            ? ` · ${pack.provider_count} ${pack.provider_count === 1 ? "engine" : "engines"}`
            : null}
        </p>
      </div>
      <Switch
        aria-labelledby={labelId}
        checked={pack.subscribed}
        disabled={disabled || pack.always_on}
        onCheckedChange={onChange}
        phoneTouch
      />
    </li>
  );
}

const s = stylex.create({
  list: {
    listStyle: "none",
    margin: 0,
    padding: 0,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    overflow: "hidden",
  },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "16px",
    padding: "14px 16px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: {
      default: tokens.colorDivider,
      ":first-child": "transparent",
    },
    backgroundColor: tokens.colorSurface,
  },
  copy: {
    minWidth: 0,
    display: "grid",
    gap: "2px",
  },
  title: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "8px",
  },
  titleText: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 550,
  },
  badge: {
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "9999px",
    padding: "1px 8px",
    color: tokens.colorMuted,
    backgroundColor: tokens.colorSurfaceRaised,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  muted: {
    margin: 0,
    marginTop: "2px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.45,
  },
  meta: {
    margin: 0,
    marginTop: "2px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
});

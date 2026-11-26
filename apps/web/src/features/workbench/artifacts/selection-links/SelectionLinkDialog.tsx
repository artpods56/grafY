"use client";

import type { ReactElement } from "react";
import * as stylex from "@stylexjs/stylex";
import { X } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { Select } from "@/components/ui/select";
import { createUuid } from "@/features/workbench/authoring/uuid";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type {
  ArtifactInteractionField,
  ArtifactViewerEffect,
} from "../artifact-interactions";
import {
  MAX_SELECTION_LINK_MAPPINGS,
  type SelectionLinkCard,
  type SelectionLinkEditor,
  type SelectionLinksAction,
} from "./selection-links-reducer";

export interface SelectionLinkDialogProps {
  editor: SelectionLinkEditor;
  cards: readonly SelectionLinkCard[];
  fields: Readonly<Record<string, readonly ArtifactInteractionField[]>>;
  dispatch: (action: SelectionLinksAction) => void;
}

const EFFECT_LABEL = {
  focus: "Zoom to it",
  filter: "Show only matching",
  highlight: "Highlight it",
} satisfies Record<ArtifactViewerEffect, string>;

const s = stylex.create({
  stack: {
    display: "grid",
    gap: tokens.space3,
  },
  section: {
    display: "grid",
    gap: "8px",
  },
  heading: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  rows: {
    display: "grid",
    gap: "8px",
  },
  row: {
    display: "grid",
    gridTemplateColumns: "1fr auto 1fr auto",
    alignItems: "center",
    gap: "8px",
  },
  arrow: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
  footer: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "8px",
    marginLeft: "auto",
  },
});

export function SelectionLinkDialog({
  editor,
  cards,
  fields,
  dispatch,
}: SelectionLinkDialogProps): ReactElement {
  const editing = editor.phase === "editing" ? editor : null;
  const source =
    editing == null
      ? null
      : (cards.find((card) => card.id === editing.draft.sourceCardId) ?? null);
  const targetId = editing?.draft.targetCardId ?? null;
  const target =
    targetId == null
      ? null
      : (cards.find((card) => card.id === targetId) ?? null);

  return (
    <Dialog
      open={editing != null && source != null}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) dispatch({ type: "cancelled" });
      }}
    >
      {editing != null && source != null ? (
        <DialogContent size="form">
          <DialogHeader>
            <DialogTitle>
              {editing.draft.bindingId !== null
                ? "Edit selection link"
                : "Link selection"}
            </DialogTitle>
            <DialogDescription>
              Selecting a row or feature in “{source.title}” shows it in another
              card.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <div {...stylex.props(s.stack)}>
              <Field label="Show it in">
                <Select
                  value={editing.draft.targetCardId ?? ""}
                  onChange={(event) =>
                    dispatch({
                      type: "target_chosen",
                      targetCardId: event.target.value,
                    })
                  }
                >
                  <option value="">Choose a card…</option>
                  {cards
                    .filter(
                      (card) =>
                        card.id !== source.id &&
                        card.capability.effects.length > 0,
                    )
                    .map((card) => (
                      <option key={card.id} value={card.id}>
                        {card.title}
                      </option>
                    ))}
                </Select>
              </Field>
              <div {...stylex.props(s.section)}>
                <h3 {...stylex.props(s.heading)}>Match on</h3>
                <div {...stylex.props(s.rows)}>
                  {editing.draft.mappings.map((mapping, index) => {
                    const sourceFields = fields[source.id] ?? [];
                    const targetFields =
                      targetId == null ? [] : (fields[targetId] ?? []);
                    const targetTitle = target?.title ?? "the other card";
                    const several = editing.draft.mappings.length > 1;
                    const sourceName = several
                      ? `Field in ${source.title}, pair ${index + 1}`
                      : `Field in ${source.title}`;
                    const targetName = several
                      ? `Field in ${targetTitle}, pair ${index + 1}`
                      : `Field in ${targetTitle}`;
                    return (
                      <div key={index} {...stylex.props(s.row)}>
                        <Select
                          aria-label={sourceName}
                          value={mapping.sourceField}
                          onChange={(event) =>
                            dispatch({
                              type: "mapping_changed",
                              index,
                              mapping: {
                                ...mapping,
                                sourceField: event.target.value,
                              },
                            })
                          }
                        >
                          <option value="">{`Field in ${source.title}`}</option>
                          {sourceFields.map((field) => (
                            <option key={field.id} value={field.id}>
                              {field.title}
                            </option>
                          ))}
                          {mapping.sourceField !== "" &&
                          !sourceFields.some(
                            (field) => field.id === mapping.sourceField,
                          ) ? (
                            <option value={mapping.sourceField}>
                              {mapping.sourceField}
                            </option>
                          ) : null}
                        </Select>
                        <span aria-hidden="true" {...stylex.props(s.arrow)}>
                          →
                        </span>
                        <Select
                          aria-label={targetName}
                          value={mapping.targetField}
                          disabled={targetId == null}
                          onChange={(event) =>
                            dispatch({
                              type: "mapping_changed",
                              index,
                              mapping: {
                                ...mapping,
                                targetField: event.target.value,
                              },
                            })
                          }
                        >
                          <option value="">{`Field in ${targetTitle}`}</option>
                          {targetFields.map((field) => (
                            <option key={field.id} value={field.id}>
                              {field.title}
                            </option>
                          ))}
                          {mapping.targetField !== "" &&
                          !targetFields.some(
                            (field) => field.id === mapping.targetField,
                          ) ? (
                            <option value={mapping.targetField}>
                              {mapping.targetField}
                            </option>
                          ) : null}
                        </Select>
                        {several ? (
                          <IconButton
                            type="button"
                            label="Remove field pair"
                            size="md"
                            onClick={() =>
                              dispatch({ type: "mapping_removed", index })
                            }
                          >
                            <X size={16} />
                          </IconButton>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                {editing.draft.mappings.length < MAX_SELECTION_LINK_MAPPINGS ? (
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => dispatch({ type: "mapping_added" })}
                  >
                    Add field pair
                  </Button>
                ) : null}
                {(fields[source.id] ?? []).length === 0 ? (
                  <Notice tone="neutral">
                    Fields appear once “{source.title}” has loaded.
                  </Notice>
                ) : null}
                {target != null && (fields[target.id] ?? []).length === 0 ? (
                  <Notice tone="neutral">
                    Fields appear once “{target.title}” has loaded.
                  </Notice>
                ) : null}
              </div>
              {target != null ? (
                <div {...stylex.props(s.section)}>
                  <h3 {...stylex.props(s.heading)}>When a row is selected</h3>
                  {target.capability.effects.map((effect) => (
                    <Checkbox
                      key={effect}
                      checked={editing.draft.effects.includes(effect)}
                      label={EFFECT_LABEL[effect]}
                      onCheckedChange={() =>
                        dispatch({ type: "effect_toggled", effect })
                      }
                    />
                  ))}
                </div>
              ) : null}
              {editing.error !== null ? (
                <Notice tone="danger">{editing.error}</Notice>
              ) : null}
              <div {...stylex.props(s.footer)}>
                {editing.draft.bindingId !== null ? (
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() => dispatch({ type: "remove_requested" })}
                  >
                    Remove link
                  </Button>
                ) : null}
                <div {...stylex.props(s.actions)}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => dispatch({ type: "cancelled" })}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    onClick={() =>
                      dispatch({
                        type: "save_requested",
                        newBindingId: `artifact-viewer-binding-${createUuid()}`,
                      })
                    }
                  >
                    Save link
                  </Button>
                </div>
              </div>
            </div>
          </DialogBody>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

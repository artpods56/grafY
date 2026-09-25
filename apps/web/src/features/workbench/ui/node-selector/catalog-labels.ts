import { type SchemaField } from "../../canvas/config-schema";
import type { Port } from "@/lib/api";

export function fieldConstraintLabel(field: SchemaField): string {
  const constraints = [field.required ? "required" : "optional"];
  if (field.type === "string-list") {
    if (field.minItems !== undefined && field.maxItems !== undefined) {
      constraints.push(`${field.minItems}–${field.maxItems} items`);
    } else if (field.minItems !== undefined) {
      constraints.push(`min ${field.minItems} items`);
    } else if (field.maxItems !== undefined) {
      constraints.push(`max ${field.maxItems} items`);
    }
    if (
      field.itemMinLength !== undefined &&
      field.itemMaxLength !== undefined
    ) {
      constraints.push(
        `${field.itemMinLength}–${field.itemMaxLength} characters per item`,
      );
    } else if (field.itemMinLength !== undefined) {
      constraints.push(`min ${field.itemMinLength} characters per item`);
    } else if (field.itemMaxLength !== undefined) {
      constraints.push(`max ${field.itemMaxLength} characters per item`);
    }
    return constraints.join(" · ");
  }
  if (field.minimum !== undefined && field.maximum !== undefined) {
    constraints.push(`${field.minimum}–${field.maximum}`);
  } else if (field.minimum !== undefined) {
    constraints.push(`min ${field.minimum}`);
  } else if (field.maximum !== undefined) {
    constraints.push(`max ${field.maximum}`);
  }
  if (field.minLength !== undefined && field.maxLength !== undefined) {
    constraints.push(`${field.minLength}–${field.maxLength} characters`);
  } else if (field.minLength !== undefined) {
    constraints.push(`min ${field.minLength} characters`);
  } else if (field.maxLength !== undefined) {
    constraints.push(`max ${field.maxLength} characters`);
  }
  return constraints.join(" · ");
}

export function portScopeLabel(port: Port): string {
  const title = port.title ?? port.name;
  return `${title} ${port.direction === "input" ? "input" : "output"}`;
}

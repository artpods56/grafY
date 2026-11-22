import type {
  CredentialScope,
  CredentialVerificationStatus,
  NodeCredentialStatus,
} from "@/lib/api";

/**
 * How a credential surface names things for a person: a provider, a
 * verification result, a key's source. Pure, so the popover, the form and the
 * settings list draw the same words and tones.
 */

export type CredentialTone = "success" | "warning" | "danger" | "neutral";

/** The badge word for a verification result. */
export const credentialStatusLabel: Record<
  CredentialVerificationStatus,
  string
> = {
  valid: "Verified",
  invalid: "Invalid",
  unverified: "Unverified",
  unreachable: "Unreachable",
  egress_blocked: "Blocked",
  unsupported: "Not checked",
};

/** What the badge's word means, for its tooltip and for a callout's lead. */
export const credentialStatusDescription: Record<
  CredentialVerificationStatus,
  string
> = {
  valid: "The provider accepted this key.",
  invalid: "The provider rejected this key.",
  unverified: "This key has not been checked yet.",
  unreachable: "The provider could not be reached to check this key.",
  egress_blocked: "The server's egress policy blocks the provider.",
  unsupported: "This provider cannot check keys.",
};

export function credentialStatusTone(
  status: CredentialVerificationStatus,
): CredentialTone {
  switch (status) {
    case "valid":
      return "success";
    case "invalid":
    case "egress_blocked":
      return "danger";
    case "unreachable":
      return "warning";
    case "unverified":
    case "unsupported":
      return "neutral";
  }
}

const PROVIDER_NAMES: Readonly<Record<string, string>> = {
  openai_compatible: "OpenAI-compatible",
  mistral: "Mistral",
  reducto: "Reducto",
  label_studio: "Label Studio",
  litellm: "LiteLLM",
  s3: "S3",
  generic: "Generic",
};

/** `openai_compatible` → `OpenAI-compatible`; an unknown kind is title-cased. */
export function providerDisplayName(kind: string): string {
  const known = PROVIDER_NAMES[kind];
  if (known) return known;
  return kind
    .split("_")
    .filter(Boolean)
    .map((word) => word[0]!.toUpperCase() + word.slice(1))
    .join(" ");
}

const FIELD_NAMES: Readonly<Record<string, string>> = {
  base_url: "Base URL",
  api_base: "API base URL",
  endpoint: "Endpoint",
  region: "Region",
};

/** A verification field's label: `base_url` → `Base URL`. */
export function credentialFieldLabel(field: string): string {
  const known = FIELD_NAMES[field];
  if (known) return known;
  const words = field.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const credentialScopeLabel: Record<CredentialScope, string> = {
  personal: "Personal",
  shared: "Shared",
};

export type CredentialSource = NodeCredentialStatus["effective_source"];

export const credentialSourceLabel: Record<CredentialSource, string> = {
  personal_credential: "Personal",
  shared_credential: "Shared",
  deployment_default: "Server default",
  inline_legacy: "Inline key",
  none: "Not set",
};

/** Who a key belongs to, said as the reason it runs. */
export const credentialSourceDescription: Record<CredentialSource, string> = {
  personal_credential: "Your personal key runs this node for you.",
  shared_credential: "A shared workspace key runs this node.",
  deployment_default: "The server's own key runs this node.",
  inline_legacy: "A key saved on this node runs it.",
  none: "No key is selected for this node.",
};

/**
 * The state a node's effective key puts its card in: a key the provider
 * refused, or a shared key that is gone, is an error; a key that could not be
 * checked or is not chosen yet needs attention.
 */
export function nodeCredentialTone(
  status: NodeCredentialStatus,
): "configured" | "needed" | "error" {
  if (status.shared_credential_missing) return "error";
  const verification = status.effective_verification_status;
  if (verification === "invalid" || verification === "egress_blocked") {
    return "error";
  }
  if (!status.configured || status.effective_source === "none") {
    return "needed";
  }
  if (verification === "unreachable") return "needed";
  return "configured";
}

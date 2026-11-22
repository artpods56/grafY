import { ApiError, request } from "./client";
import type { components } from "./generated/grafy";

type Schemas = components["schemas"];
export type Credential = Schemas["CredentialResponse"];
export type CredentialScope = Schemas["CredentialScope"];
export type CredentialVerification = Schemas["CredentialVerificationResponse"];
export type CredentialVerificationStatus =
  Schemas["CredentialVerificationStatus"];
export type CreateCredential = Schemas["CreateCredentialRequest"];
export type UpdateCredential = Schemas["UpdateCredentialRequest"];
export type SharedCredentialBinding = Schemas["SharedCredentialBindingRequest"];
export type PersonalCredentialSelection =
  Schemas["PersonalCredentialSelectionRequest"];
export type CredentialVerificationConfig = NonNullable<
  CreateCredential["verify_config"]
>;
export type NodeCredentialStatus = Schemas["NodeSecretStatusResponse"];

export type CredentialLocation =
  { scope: "personal" } | { scope: "shared"; workspaceId: string };

function credentialsPath(location: CredentialLocation): string {
  return location.scope === "personal"
    ? "/v1/me/credentials"
    : `/v1/workspaces/${encodeURIComponent(location.workspaceId)}/credentials`;
}

export async function listCredentials(
  location: CredentialLocation,
  providerKind?: string,
  signal?: AbortSignal,
): Promise<readonly Credential[]> {
  const path = credentialsPath(location);
  const query = providerKind
    ? `?provider_kind=${encodeURIComponent(providerKind)}`
    : "";
  const result = await request<Schemas["CredentialListResponse"]>(
    "GET",
    path + query,
    { signal },
  );
  return result.credentials;
}

export function createCredential(
  location: CredentialLocation,
  body: CreateCredential,
) {
  return request<Credential>("POST", credentialsPath(location), { body });
}

export function updateCredential(
  location: CredentialLocation,
  id: string,
  body: UpdateCredential,
) {
  return request<Credential>(
    "PATCH",
    `${credentialsPath(location)}/${encodeURIComponent(id)}`,
    { body },
  );
}

export function deleteCredential(location: CredentialLocation, id: string) {
  return request<void>(
    "DELETE",
    `${credentialsPath(location)}/${encodeURIComponent(id)}`,
  );
}

export function verifyCredential(
  location: CredentialLocation,
  body: Schemas["VerifyCandidateCredentialRequest"],
) {
  return request<CredentialVerification>(
    "POST",
    `${credentialsPath(location)}/verify`,
    { body },
  );
}

export function reverifyCredential(
  location: CredentialLocation,
  id: string,
  body?: Schemas["VerifySavedCredentialRequest"],
) {
  return request<Credential>(
    "POST",
    `${credentialsPath(location)}/${encodeURIComponent(id)}/verify`,
    { body },
  );
}

export interface NodeCredentialAddress {
  workspaceId: string;
  projectId: string;
  graphId: string;
  nodeId: string;
  name: string;
}

function nodeSecretPath(address: NodeCredentialAddress): string {
  const { workspaceId, projectId, graphId, nodeId, name } = address;
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/secrets/${encodeURIComponent(name)}`;
}

export function setSharedBinding(
  address: NodeCredentialAddress,
  body: SharedCredentialBinding,
) {
  return request<NodeCredentialStatus>(
    "PUT",
    `${nodeSecretPath(address)}/shared-binding`,
    { body },
  );
}

export function setPersonalSelection(
  address: NodeCredentialAddress,
  body: PersonalCredentialSelection,
) {
  return request<NodeCredentialStatus>(
    "PUT",
    `${nodeSecretPath(address)}/personal-selection`,
    { body },
  );
}

export function verifyNodeSecret(
  address: NodeCredentialAddress,
  body?: Schemas["VerifyNodeSecretRequest"],
) {
  return request<CredentialVerification>(
    "POST",
    `${nodeSecretPath(address)}/verify`,
    { body },
  );
}

export function credentialVerificationFailure(error: unknown): {
  message: string;
  canSave: boolean;
} {
  if (!(error instanceof ApiError)) {
    return {
      message: "Could not complete the credential request.",
      canSave: false,
    };
  }
  if (error.status === 422) {
    try {
      const payload: unknown = JSON.parse(error.detail);
      if (payload && typeof payload === "object" && "detail" in payload) {
        const detail = payload.detail;
        if (detail && typeof detail === "object" && "verification" in detail) {
          const verification = detail.verification;
          if (
            verification &&
            typeof verification === "object" &&
            "message" in verification &&
            typeof verification.message === "string"
          ) {
            return {
              message: verification.message,
              canSave:
                "can_save_unverified" in detail &&
                detail.can_save_unverified === true,
            };
          }
        }
      }
    } catch {
      // Other validation errors use plain text.
    }
  }
  return { message: error.detail, canSave: false };
}

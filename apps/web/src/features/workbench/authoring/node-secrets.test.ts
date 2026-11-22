import { describe, expect, it } from "vitest";

import type { NodeSpec } from "@/lib/api";
import {
  nodeSecretBindingReady,
  nodeSecretDependencyRevision,
  nodeSecretInputs,
  reconciledNodeSecretStatuses,
} from "./node-secrets";

function secretNodeSpec(): NodeSpec {
  return {
    operator_id: "llm.openai.completion",
    operator_version: 1,
    plugin_slug: "external.llm",
    origin: "builtin",
    title: "OpenAI-compatible completion",
    description: "Completes a prompt through an OpenAI-compatible API.",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
    secret_inputs: [
      {
        name: "api_key",
        title: "API key",
        description: "OpenAI-compatible bearer credential.",
        config_dependencies: ["base_url"],
      },
    ],
  };
}

describe("write-only node secret metadata", () => {
  it("reads declared inputs without manufacturing a secret value", () => {
    expect(nodeSecretInputs(secretNodeSpec())).toEqual([
      {
        name: "api_key",
        title: "API key",
        description: "OpenAI-compatible bearer credential.",
        configDependencies: ["base_url"],
      },
    ]);
  });

  it("maps status-only API records and defaults omitted secrets to unconfigured", () => {
    const spec = secretNodeSpec();

    expect(reconciledNodeSecretStatuses(spec, "llm-1", [])).toEqual({
      api_key: { state: "unconfigured" },
    });
    expect(
      reconciledNodeSecretStatuses(spec, "llm-1", [
        { node_id: "other", name: "api_key", configured: true },
        { node_id: "llm-1", name: "api_key", configured: true },
      ]),
    ).toEqual({
      api_key: { state: "configured" },
    });
  });

  it("changes the transient input identity only when a dependency changes", () => {
    const input = nodeSecretInputs(secretNodeSpec())[0]!;
    const first = nodeSecretDependencyRevision(input, {
      base_url: "https://api.openai.com/v1",
      model: "gpt-4.1-mini",
    });
    const sameEndpoint = nodeSecretDependencyRevision(input, {
      base_url: "https://api.openai.com/v1",
      model: "gpt-5-mini",
    });
    const otherEndpoint = nodeSecretDependencyRevision(input, {
      base_url: "https://openrouter.ai/api/v1",
      model: "gpt-5-mini",
    });

    expect(sameEndpoint).toBe(first);
    expect(otherEndpoint).not.toBe(first);
  });

  it("keeps a binding ready across unrelated graph and node config edits", () => {
    const input = nodeSecretInputs(secretNodeSpec())[0]!;
    const savedNode = {
      id: "llm-1",
      kind: "builtin",
      operator_id: "llm.openai.completion",
      operator_version: 1,
      config: {
        base_url: "https://api.openai.com/v1",
        model: "gpt-5-mini",
      },
    };

    expect(
      nodeSecretBindingReady(
        input,
        {
          ...savedNode,
          config: {
            ...savedNode.config,
            model: "gpt-5.1-mini",
            temperature: 0.4,
          },
        },
        savedNode,
      ),
    ).toBe(true);
  });

  it("rejects changed dependencies, changed operators, and missing saved nodes", () => {
    const input = nodeSecretInputs(secretNodeSpec())[0]!;
    const savedNode = {
      id: "llm-1",
      kind: "builtin",
      operator_id: "llm.openai.completion",
      operator_version: 1,
      config: { base_url: "https://api.openai.com/v1" },
    };

    expect(
      nodeSecretBindingReady(
        input,
        {
          ...savedNode,
          config: { base_url: "https://openrouter.ai/api/v1" },
        },
        savedNode,
      ),
    ).toBe(false);
    expect(
      nodeSecretBindingReady(
        input,
        {
          ...savedNode,
          id: "llm-2",
        },
        savedNode,
      ),
    ).toBe(false);
    expect(
      nodeSecretBindingReady(
        input,
        {
          ...savedNode,
          operator_id: "llm.other.completion",
        },
        savedNode,
      ),
    ).toBe(false);
    expect(
      nodeSecretBindingReady(
        input,
        {
          ...savedNode,
          operator_version: 2,
        },
        savedNode,
      ),
    ).toBe(false);
    expect(nodeSecretBindingReady(input, savedNode, undefined)).toBe(false);
  });

  it("evaluates multiple secret inputs independently", () => {
    const baseSpec = secretNodeSpec();
    const spec: NodeSpec = {
      ...baseSpec,
      secret_inputs: [
        ...(baseSpec.secret_inputs ?? []),
        {
          name: "organization_key",
          title: "Organization key",
          config_dependencies: ["organization"],
        },
      ],
    };
    const [apiKey, organizationKey] = nodeSecretInputs(spec);
    const savedNode = {
      id: "llm-1",
      kind: "builtin",
      operator_id: spec.operator_id,
      operator_version: spec.operator_version,
      config: {
        base_url: "https://api.openai.com/v1",
        organization: "org-one",
      },
    };
    const currentNode = {
      ...savedNode,
      config: { ...savedNode.config, organization: "org-two" },
    };

    expect(nodeSecretBindingReady(apiKey!, currentNode, savedNode)).toBe(true);
    expect(
      nodeSecretBindingReady(organizationKey!, currentNode, savedNode),
    ).toBe(false);
  });

  it("restores readiness when a dependency is reverted to its saved value", () => {
    const input = nodeSecretInputs(secretNodeSpec())[0]!;
    const savedNode = {
      id: "llm-1",
      kind: "builtin",
      operator_id: "llm.openai.completion",
      operator_version: 1,
      config: { base_url: "https://api.openai.com/v1" },
    };
    const changedNode = {
      ...savedNode,
      config: { base_url: "https://openrouter.ai/api/v1" },
    };
    const revertedNode = {
      ...changedNode,
      config: { base_url: savedNode.config.base_url },
    };

    expect(nodeSecretBindingReady(input, changedNode, savedNode)).toBe(false);
    expect(nodeSecretBindingReady(input, revertedNode, savedNode)).toBe(true);
  });
});

import type { NodeRegistry } from "@/lib/api";

/**
 * The "Ask a model" node (`llm.openai_compatible.chat_completion`) exactly as
 * the API's node registry served it from the LLM plugin on 2026-11-20, with the
 * three artifact types its ports use. Refresh it from
 * `GET /v1/workspaces/{id}/nodes` when the plugin's ports or config change.
 */
export const ASK_A_MODEL_OPERATOR_ID = "llm.openai_compatible.chat_completion";

export const askAModelRegistry: NodeRegistry = {
  plugins: [
    {
      slug: "external.llm",
      title: "Language model",
      origin: "builtin",
      entry_kind: "plugin",
    },
  ],
  artifact_types: [
    {
      key: {
        id: "prompt.message",
        schema_version: 2,
      },
      title: "Instruction",
      payload_schema: {
        $defs: {
          ArtifactRef: {
            properties: {
              artifact_id: {
                format: "uuid",
                title: "Artifact Id",
                type: "string",
              },
              artifact_type: {
                title: "Artifact Type",
                type: "string",
              },
              schema_version: {
                title: "Schema Version",
                type: "integer",
              },
              content_hash: {
                anyOf: [
                  {
                    type: "string",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                title: "Content Hash",
              },
            },
            required: ["artifact_id", "artifact_type", "schema_version"],
            title: "ArtifactRef",
            type: "object",
          },
          PromptMessageRole: {
            enum: ["system", "user"],
            title: "PromptMessageRole",
            type: "string",
          },
        },
        additionalProperties: false,
        properties: {
          role: {
            $ref: "#/$defs/PromptMessageRole",
          },
          text: {
            title: "Text",
            type: "string",
          },
          image_refs: {
            items: {
              $ref: "#/$defs/ArtifactRef",
            },
            title: "Image Refs",
            type: "array",
          },
        },
        required: ["role", "text"],
        title: "PromptMessage",
        type: "object",
      },
      field_projections: [
        {
          path: ["role"],
          target_artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          title: "PromptMessageRole",
        },
        {
          path: ["text"],
          target_artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          title: "Text",
        },
      ],
      materialized_json_type: null,
      export_formats: [],
      extensions: [],
      confirmation_rule: {
        rule: "none",
        signatures: [],
      },
      bundle: {
        format: "inline-json",
        version: 1,
      },
    },
    {
      key: {
        id: "json.schema",
        schema_version: 1,
      },
      title: "Answer format",
      payload_schema: {
        additionalProperties: false,
        properties: {
          value: {
            title: "Value",
            type: "string",
          },
        },
        required: ["value"],
        title: "JsonSchemaPayload",
        type: "object",
      },
      field_projections: [
        {
          path: ["value"],
          target_artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          title: "Value",
        },
      ],
      materialized_json_type: null,
      export_formats: [],
      extensions: [],
      confirmation_rule: {
        rule: "none",
        signatures: [],
      },
      bundle: {
        format: "inline-json",
        version: 1,
      },
    },
    {
      key: {
        id: "llm.completion",
        schema_version: 1,
      },
      title: "LLM completion",
      payload_schema: {
        additionalProperties: false,
        description:
          "Provider-neutral Chat Completions result safe for artifact persistence.",
        properties: {
          content: {
            description: "Assistant message content returned by the provider.",
            title: "Content",
            type: "string",
          },
          structured_value: {
            anyOf: [
              {
                additionalProperties: true,
                type: "object",
              },
              {
                type: "null",
              },
            ],
            default: null,
            description:
              "Parsed and validated object when a JSON Schema was requested.",
            title: "Structured Value",
          },
          model: {
            minLength: 1,
            title: "Model",
            type: "string",
          },
          protocol: {
            const: "openai_chat_completions",
            default: "openai_chat_completions",
            title: "Protocol",
            type: "string",
          },
          base_url: {
            description: "OpenAI-compatible API base URL used for the request.",
            minLength: 1,
            title: "Base Url",
            type: "string",
          },
          response_id: {
            anyOf: [
              {
                type: "string",
              },
              {
                type: "null",
              },
            ],
            default: null,
            title: "Response Id",
          },
          finish_reason: {
            anyOf: [
              {
                type: "string",
              },
              {
                type: "null",
              },
            ],
            default: null,
            title: "Finish Reason",
          },
          message_count: {
            minimum: 1,
            title: "Message Count",
            type: "integer",
          },
          source_image_artifact_ids: {
            items: {
              format: "uuid",
              type: "string",
            },
            title: "Source Image Artifact Ids",
            type: "array",
          },
          schema: {
            anyOf: [
              {
                type: "string",
              },
              {
                type: "null",
              },
            ],
            default: null,
            description:
              "JSON Schema text requested from the provider, when present.",
            title: "Schema",
          },
          schema_name: {
            anyOf: [
              {
                minLength: 1,
                type: "string",
              },
              {
                type: "null",
              },
            ],
            default: null,
            title: "Schema Name",
          },
          schema_strict: {
            anyOf: [
              {
                type: "boolean",
              },
              {
                type: "null",
              },
            ],
            default: null,
            title: "Schema Strict",
          },
          usage: {
            additionalProperties: true,
            title: "Usage",
            type: "object",
          },
        },
        required: ["content", "model", "base_url", "message_count"],
        title: "CompletionPayload",
        type: "object",
      },
      field_projections: [
        {
          path: ["base_url"],
          target_artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          title: "Base Url",
        },
        {
          path: ["content"],
          target_artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          title: "Content",
        },
        {
          path: ["message_count"],
          target_artifact_type: {
            id: "scalar.integer",
            schema_version: 1,
          },
          title: "Message Count",
        },
        {
          path: ["model"],
          target_artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          title: "Model",
        },
        {
          path: ["protocol"],
          target_artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          title: "Protocol",
        },
      ],
      materialized_json_type: null,
      export_formats: [],
      extensions: [],
      confirmation_rule: {
        rule: "none",
        signatures: [],
      },
      bundle: {
        format: "inline-json",
        version: 1,
      },
    },
  ],
  artifact_conversions: [],
  nodes: [
    {
      origin: "builtin",
      operator_id: "llm.openai_compatible.chat_completion",
      operator_version: 1,
      plugin_slug: "external.llm",
      title: "Ask a model",
      description:
        "Sends the instructions to a chat model and keeps the answer.",
      config_schema: {
        additionalProperties: false,
        properties: {
          base_url: {
            default: "https://api.openai.com/v1",
            description:
              "OpenAI-compatible API base URL, including its version path.",
            minLength: 1,
            title: "Base Url",
            type: "string",
          },
          model: {
            default: "gpt-4.1-mini",
            description: "Provider model identifier.",
            minLength: 1,
            title: "Model",
            type: "string",
          },
          temperature: {
            default: 0.0,
            description: "Sampling temperature passed to the provider.",
            maximum: 2.0,
            minimum: 0.0,
            title: "Temperature",
            type: "number",
          },
          max_completion_tokens: {
            default: 2048,
            description: "Maximum number of generated tokens.",
            maximum: 1000000,
            minimum: 1,
            title: "Max Completion Tokens",
            type: "integer",
          },
          timeout_ms: {
            default: 120000,
            description: "Maximum provider request time in milliseconds.",
            maximum: 900000,
            minimum: 1000,
            title: "Timeout Ms",
            type: "integer",
          },
          max_retries: {
            default: 0,
            description:
              "Maximum SDK retries after a failed provider request. Keep at zero when duplicate provider calls are unacceptable.",
            maximum: 5,
            minimum: 0,
            title: "Max Retries",
            type: "integer",
          },
          schema_name: {
            default: "structured_response",
            description:
              "Provider-facing name used when a JSON Schema is connected.",
            maxLength: 64,
            minLength: 1,
            pattern: "^[a-zA-Z0-9_-]+$",
            title: "Schema Name",
            type: "string",
          },
          strict: {
            default: true,
            description:
              "Whether the provider must enforce a connected JSON Schema.",
            title: "Strict",
            type: "boolean",
          },
        },
        title: "OpenAICompatibleConfig",
        type: "object",
      },
      input_schema: {
        $defs: {
          ArtifactRef: {
            properties: {
              artifact_id: {
                format: "uuid",
                title: "Artifact Id",
                type: "string",
              },
              artifact_type: {
                title: "Artifact Type",
                type: "string",
              },
              schema_version: {
                title: "Schema Version",
                type: "integer",
              },
              content_hash: {
                anyOf: [
                  {
                    type: "string",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                title: "Content Hash",
              },
            },
            required: ["artifact_id", "artifact_type", "schema_version"],
            title: "ArtifactRef",
            type: "object",
          },
          PromptMessage: {
            additionalProperties: false,
            properties: {
              role: {
                $ref: "#/$defs/PromptMessageRole",
              },
              text: {
                title: "Text",
                type: "string",
              },
              image_refs: {
                items: {
                  $ref: "#/$defs/ArtifactRef",
                },
                title: "Image Refs",
                type: "array",
              },
            },
            required: ["role", "text"],
            title: "PromptMessage",
            type: "object",
          },
          PromptMessageRole: {
            enum: ["system", "user"],
            title: "PromptMessageRole",
            type: "string",
          },
        },
        additionalProperties: false,
        properties: {
          messages: {
            description: "Ordered prompt messages.",
            items: {
              $ref: "#/$defs/PromptMessage",
            },
            minItems: 1,
            title: "Instructions",
            type: "array",
          },
          json_schema: {
            anyOf: [
              {
                type: "string",
              },
              {
                type: "null",
              },
            ],
            default: null,
            description: "Optional schema for a structured completion.",
            title: "Answer format",
          },
        },
        required: ["messages"],
        title: "OpenAICompatibleInput",
        type: "object",
      },
      output_schema: {
        $defs: {
          CompletionPayload: {
            additionalProperties: false,
            description:
              "Provider-neutral Chat Completions result safe for artifact persistence.",
            properties: {
              content: {
                description:
                  "Assistant message content returned by the provider.",
                title: "Content",
                type: "string",
              },
              structured_value: {
                anyOf: [
                  {
                    additionalProperties: true,
                    type: "object",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                description:
                  "Parsed and validated object when a JSON Schema was requested.",
                title: "Structured Value",
              },
              model: {
                minLength: 1,
                title: "Model",
                type: "string",
              },
              protocol: {
                const: "openai_chat_completions",
                default: "openai_chat_completions",
                title: "Protocol",
                type: "string",
              },
              base_url: {
                description:
                  "OpenAI-compatible API base URL used for the request.",
                minLength: 1,
                title: "Base Url",
                type: "string",
              },
              response_id: {
                anyOf: [
                  {
                    type: "string",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                title: "Response Id",
              },
              finish_reason: {
                anyOf: [
                  {
                    type: "string",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                title: "Finish Reason",
              },
              message_count: {
                minimum: 1,
                title: "Message Count",
                type: "integer",
              },
              source_image_artifact_ids: {
                items: {
                  format: "uuid",
                  type: "string",
                },
                title: "Source Image Artifact Ids",
                type: "array",
              },
              schema: {
                anyOf: [
                  {
                    type: "string",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                description:
                  "JSON Schema text requested from the provider, when present.",
                title: "Schema",
              },
              schema_name: {
                anyOf: [
                  {
                    minLength: 1,
                    type: "string",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                title: "Schema Name",
              },
              schema_strict: {
                anyOf: [
                  {
                    type: "boolean",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
                title: "Schema Strict",
              },
              usage: {
                additionalProperties: true,
                title: "Usage",
                type: "object",
              },
            },
            required: ["content", "model", "base_url", "message_count"],
            title: "CompletionPayload",
            type: "object",
          },
        },
        additionalProperties: false,
        properties: {
          completion: {
            $ref: "#/$defs/CompletionPayload",
            description: "Completion content and safe provider metadata.",
            title: "Answer",
          },
        },
        required: ["completion"],
        title: "OpenAICompatibleOutput",
        type: "object",
      },
      inputs: [
        {
          kind: "artifact",
          name: "messages",
          title: "Instructions",
          description: "Ordered prompt messages.",
          direction: "input",
          artifact_type: {
            id: "prompt.message",
            schema_version: 2,
          },
          artifact_type_variable: null,
          also_accepts: [],
          shape: "many",
          accepted_shapes: ["many"],
          instance_plugs: false,
          variadic: false,
          required: true,
          shape_field: null,
          agent_default: null,
        },
        {
          kind: "artifact",
          name: "json_schema",
          title: "Answer format",
          description: "Optional schema for a structured completion.",
          direction: "input",
          artifact_type: {
            id: "json.schema",
            schema_version: 1,
          },
          artifact_type_variable: null,
          also_accepts: [],
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: false,
          shape_field: null,
          agent_default: null,
        },
      ],
      outputs: [
        {
          kind: "artifact",
          name: "completion",
          title: "Answer",
          description: "Completion content and safe provider metadata.",
          direction: "output",
          artifact_type: {
            id: "llm.completion",
            schema_version: 1,
          },
          artifact_type_variable: null,
          also_accepts: [],
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: true,
          shape_field: null,
          agent_default: null,
        },
      ],
      secret_inputs: [
        {
          name: "api_key",
          config_dependencies: ["base_url"],
          provider_kind: "openai_compatible",
          supports_verification: true,
          title: "API key",
          description:
            "Write-only bearer credential for the configured API base URL.",
        },
      ],
      catalog_visible: true,
      runnable: true,
    },
  ],
};

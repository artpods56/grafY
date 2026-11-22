import type { NodeRegistry } from "@/lib/api";

// Text input and Schema Builder from the builtin catalog response.
export const canvasNodeRegistry: NodeRegistry = {
  plugins: [
    {
      slug: "text",
      title: "Text",
      origin: "builtin",
      entry_kind: "plugin",
    },
    {
      slug: "schema",
      title: "Schema",
      origin: "builtin",
      entry_kind: "plugin",
    },
  ],
  artifact_types: [
    {
      key: {
        id: "scalar.text",
        schema_version: 1,
      },
      title: "Text",
      payload_schema: {
        additionalProperties: false,
        properties: {
          value: {
            title: "Value",
            type: "string",
          },
        },
        required: ["value"],
        title: "TextValue",
        type: "object",
      },
      field_projections: [],
      materialized_json_type: "string",
      export_formats: [
        {
          format: "txt",
          content_type: "text/plain; charset=utf-8",
          filename: "text.txt",
        },
      ],
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
      operator_id: "text.input",
      operator_version: 1,
      plugin_slug: "text",
      title: "Text input",
      description: "Produces one configured multiline text value.",
      config_schema: {
        additionalProperties: false,
        properties: {
          text: {
            description: "Multiline text emitted by the node.",
            format: "textarea",
            title: "Text",
            type: "string",
          },
        },
        required: ["text"],
        title: "TextInputConfig",
        type: "object",
      },
      input_schema: {
        additionalProperties: false,
        properties: {},
        title: "TextInputInput",
        type: "object",
      },
      output_schema: {
        additionalProperties: false,
        properties: {
          text: {
            description: "The configured text value.",
            title: "Text",
            type: "string",
          },
        },
        required: ["text"],
        title: "TextInputOutput",
        type: "object",
      },
      inputs: [],
      outputs: [
        {
          name: "text",
          title: null,
          description: "The configured text value.",
          direction: "output",
          kind: "artifact",
          artifact_type: {
            id: "scalar.text",
            schema_version: 1,
          },
          artifact_type_variable: null,
          also_accepts: [],
          service_contracts: [],
          features: [],
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: true,
          shape_field: null,
          agent_default: null,
        },
      ],
      secret_inputs: [],
      catalog_visible: true,
      runnable: true,
    },
    {
      origin: "builtin",
      operator_id: "schema.builder",
      operator_version: 1,
      plugin_slug: "schema",
      title: "Schema Builder",
      description:
        "Builds one object JSON Schema with optional connected child schemas.",
      config_schema: {
        $defs: {
          JsonSchemaBuilderField: {
            additionalProperties: false,
            properties: {
              id: {
                description:
                  "Stable field identifier and instance-plug identifier.",
                maxLength: 255,
                minLength: 1,
                title: "Id",
                type: "string",
              },
              name: {
                description: "Property name emitted in the object schema.",
                minLength: 1,
                title: "Name",
                type: "string",
              },
              kind: {
                $ref: "#/$defs/SchemaFieldKind",
              },
              required: {
                default: false,
                title: "Required",
                type: "boolean",
              },
              description: {
                default: "",
                title: "Description",
                type: "string",
              },
              item_kind: {
                anyOf: [
                  {
                    $ref: "#/$defs/SchemaSequenceItemKind",
                  },
                  {
                    type: "null",
                  },
                ],
                default: null,
              },
            },
            required: ["id", "name", "kind"],
            title: "JsonSchemaBuilderField",
            type: "object",
          },
          SchemaFieldKind: {
            enum: [
              "string",
              "integer",
              "number",
              "boolean",
              "sequence",
              "schema",
            ],
            title: "SchemaFieldKind",
            type: "string",
          },
          SchemaSequenceItemKind: {
            enum: ["string", "integer", "number", "boolean", "schema"],
            title: "SchemaSequenceItemKind",
            type: "string",
          },
        },
        additionalProperties: false,
        properties: {
          title: {
            default: "",
            description:
              "Optional title included in the generated object schema.",
            title: "Title",
            type: "string",
          },
          description: {
            default: "",
            description:
              "Optional description included in the generated object schema.",
            title: "Description",
            type: "string",
          },
          additional_properties: {
            default: false,
            description:
              "Whether properties not declared by the builder are allowed.",
            title: "Additional Properties",
            type: "boolean",
          },
          fields: {
            description: "Ordered fields in the generated object schema.",
            items: {
              $ref: "#/$defs/JsonSchemaBuilderField",
            },
            title: "Fields",
            type: "array",
          },
        },
        title: "JsonSchemaBuilderConfig",
        type: "object",
      },
      input_schema: {
        $defs: {
          JsonSchemaText: {
            additionalProperties: false,
            properties: {
              value: {
                title: "Value",
                type: "string",
              },
            },
            required: ["value"],
            title: "JsonSchemaText",
            type: "object",
          },
        },
        additionalProperties: false,
        properties: {
          schemas: {
            description:
              "Connected child schemas in the order of schema-consuming fields.",
            items: {
              $ref: "#/$defs/JsonSchemaText",
            },
            title: "Schemas",
            type: "array",
          },
        },
        title: "JsonSchemaBuilderInput",
        type: "object",
      },
      output_schema: {
        $defs: {
          JsonSchemaText: {
            additionalProperties: false,
            properties: {
              value: {
                title: "Value",
                type: "string",
              },
            },
            required: ["value"],
            title: "JsonSchemaText",
            type: "object",
          },
        },
        additionalProperties: false,
        properties: {
          json_schema: {
            $ref: "#/$defs/JsonSchemaText",
            description: "Canonical Draft 2020-12 object JSON Schema text.",
            title: "JSON Schema",
          },
        },
        required: ["json_schema"],
        title: "JsonSchemaBuilderOutput",
        type: "object",
      },
      inputs: [
        {
          name: "schemas",
          title: null,
          description:
            "Connected child schemas in the order of schema-consuming fields.",
          direction: "input",
          kind: "artifact",
          artifact_type: {
            id: "json.schema",
            schema_version: 1,
          },
          artifact_type_variable: null,
          also_accepts: [],
          service_contracts: [],
          features: [],
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: true,
          variadic: true,
          required: false,
          shape_field: null,
          agent_default: null,
        },
      ],
      outputs: [
        {
          name: "json_schema",
          title: "JSON Schema",
          description: "Canonical Draft 2020-12 object JSON Schema text.",
          direction: "output",
          kind: "artifact",
          artifact_type: {
            id: "json.schema",
            schema_version: 1,
          },
          artifact_type_variable: null,
          also_accepts: [],
          service_contracts: [],
          features: [],
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: true,
          shape_field: null,
          agent_default: null,
        },
      ],
      secret_inputs: [],
      catalog_visible: true,
      runnable: true,
    },
  ],
};

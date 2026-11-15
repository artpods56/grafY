#!/usr/bin/env python3
"""Deterministic HTTPS provider for Grafy's live execution tests."""

import argparse
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import sys
from typing import NoReturn, cast, override


def has_non_empty_text(document: dict[object, object]) -> bool:
    messages = document.get("messages")
    if not isinstance(messages, list):
        return False
    for message_value in cast(list[object], messages):
        if not isinstance(message_value, dict):
            continue
        message = cast(dict[object, object], message_value)
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return True
        if not isinstance(content, list):
            continue
        for part_value in cast(list[object], content):
            if not isinstance(part_value, dict):
                continue
            part = cast(dict[object, object], part_value)
            text = part.get("text")
            if part.get("type") == "text" and isinstance(text, str) and text.strip():
                return True
    return False


def has_inline_image(document: dict[object, object]) -> bool:
    messages = document.get("messages")
    if not isinstance(messages, list):
        return False
    for message_value in cast(list[object], messages):
        if not isinstance(message_value, dict):
            continue
        message = cast(dict[object, object], message_value)
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part_value in cast(list[object], content):
            if not isinstance(part_value, dict):
                continue
            part = cast(dict[object, object], part_value)
            image_url_value = part.get("image_url")
            if part.get("type") != "image_url" or not isinstance(image_url_value, dict):
                continue
            image_url = cast(dict[object, object], image_url_value)
            url = image_url.get("url")
            if not isinstance(url, str):
                continue
            metadata, separator, encoded = url.partition(",")
            if (
                not separator
                or not metadata.startswith("data:image/")
                or not metadata.endswith(";base64")
                or not encoded
            ):
                continue
            try:
                base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                continue
            return True
    return False


class OpenAIProviderServer(ThreadingHTTPServer):
    api_key: str

    def __init__(
        self,
        server_address: tuple[str, int],
        api_key: str,
    ) -> None:
        super().__init__(server_address, OpenAIProviderHandler)
        self.api_key = api_key


class OpenAIProviderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/healthz":
            self._send_json(404, {"error": "not_found"})
            return
        self._send_json(200, {"status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "not_found"})
            return
        server = cast(OpenAIProviderServer, self.server)
        if self.headers.get("Authorization") != f"Bearer {server.api_key}":
            self._send_json(
                401,
                {
                    "error": {
                        "message": "The E2E provider did not accept the API key.",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            parsed_body = cast(object, json.loads(self.rfile.read(content_length)))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid_json"})
            return
        document = (
            cast(dict[object, object], parsed_body)
            if isinstance(parsed_body, dict)
            else {}
        )
        model = document.get("model")
        if not isinstance(model, str) or not model:
            self._send_json(400, {"error": "invalid_model"})
            return
        if not has_non_empty_text(document):
            self._send_json(
                400,
                {
                    "error": {
                        "message": "E2E provider requires non-empty text content.",
                        "type": "invalid_request_error",
                        "param": "messages",
                        "code": "missing_text",
                    }
                },
            )
            return
        if not has_inline_image(document):
            self._send_json(
                400,
                {
                    "error": {
                        "message": "E2E provider requires one inline image.",
                        "type": "invalid_request_error",
                        "param": "messages",
                        "code": "missing_image",
                    }
                },
            )
            return

        self._send_json(
            200,
            {
                "id": "chatcmpl-grafy-e2e",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "The request contained text and one image.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 8,
                    "total_tokens": 19,
                },
            },
        )

    @override
    def log_message(self, format: str, *args: object) -> None:
        print(
            f"openai-e2e {self.command} {self.path}: {format % args}",
            file=sys.stderr,
        )

    def _send_json(self, status: int, payload: object) -> None:
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="grafy-e2e-openai-provider")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--api-key", required=True)
    return parser.parse_args()


def main() -> NoReturn:
    args = parse_args()
    server = OpenAIProviderServer((args.host, args.port), args.api_key)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.certificate, args.private_key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
    raise RuntimeError("E2E provider stopped unexpectedly")


if __name__ == "__main__":
    main()

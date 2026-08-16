from grafy_agent.errors import terminal_error


class UnrenderableProviderError(RuntimeError):
    def __str__(self) -> str:
        raise RuntimeError("exception rendering failed")


def test_terminal_error_redacts_quoted_headers_and_credentials() -> None:
    error = RuntimeError(
        "SDK request failed\n"
        "headers={'Authorization': 'Bearer bearer-secret', "
        '"X-Api-Key": "api-key-secret"} '
        "client_secret='client-secret' "
        "url=https://sdk-user:sdk-password@provider.example/error?access_token="
        "query-secret"
    )

    rendered = terminal_error("Daytona sandbox request", error)

    assert "bearer-secret" not in rendered
    assert "api-key-secret" not in rendered
    assert "client-secret" not in rendered
    assert "sdk-user" not in rendered
    assert "sdk-password" not in rendered
    assert "query-secret" not in rendered
    assert rendered.count("[redacted]") >= 5
    assert "\n" not in rendered


def test_terminal_error_is_bounded_when_provider_detail_is_oversized() -> None:
    rendered = terminal_error(
        "Sandbox provider operation",
        RuntimeError("x" * 10_000),
    )

    assert len(rendered) <= 3_900
    assert "truncated from" in rendered


def test_terminal_error_survives_exception_with_broken_string_rendering() -> None:
    rendered = terminal_error(
        "Sandbox provider operation",
        UnrenderableProviderError(),
    )

    assert rendered == (
        "Sandbox provider operation failed (UnrenderableProviderError): "
        "exception detail unavailable"
    )

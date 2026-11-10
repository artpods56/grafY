"""OIDC failures kept inside the auth owner until a route translates them."""


class OidcProtocolError(Exception):
    """A bounded OIDC failure safe to expose as a generic HTTP error."""

    def __init__(self, code: str, *, transaction_consumed: bool = False) -> None:
        self.code = code
        self.transaction_consumed = transaction_consumed
        super().__init__(code)


class OidcCallbackInternalError(Exception):
    """Safe internal callback failure with transaction lifecycle state."""

    def __init__(self, *, transaction_consumed: bool) -> None:
        self.transaction_consumed = transaction_consumed
        super().__init__("callback_internal_error")


def require_oidc_configuration(configured: bool) -> None:
    if not configured:
        raise OidcProtocolError("oidc_not_configured")


def require_config_value(value: str | None) -> str:
    if value is None or not value.strip():
        raise OidcProtocolError("oidc_not_configured")
    return value

"""Safe provider-error categories; never retain upstream messages or payloads."""

NON_RETRYABLE_CATEGORIES = frozenset({
    "context_length_exceeded", "invalid_request_error", "invalid_argument",
    "insufficient_quota", "insufficient_balance", "invalid_api_key",
    "model_not_found", "content_filter", "data_inspection_failed",
})
KNOWN_CATEGORIES = NON_RETRYABLE_CATEGORIES | {
    "rate_limit_exceeded", "service_unavailable", "internal_server_error",
    "overloaded_error", "timeout_error",
}
_ALIASES = {"DataInspectionFailed": "data_inspection_failed"}


def provider_error(response):
    extra = getattr(response, "model_extra", None)
    return (extra.get("error") if isinstance(extra, dict) else None) or getattr(response, "error", None)


def provider_error_category(response):
    error = provider_error(response)
    if not error:
        return None
    for field in ("code", "type"):
        value = error.get(field) if isinstance(error, dict) else getattr(error, field, None)
        if isinstance(value, str):
            category = _ALIASES.get(value, value)
            if category in KNOWN_CATEGORIES:
                return category
    return "unclassified"


class ProviderResponseError(RuntimeError):
    def __init__(self, category):
        # A raw upstream value must never enter exception text or the ledger.
        self.category = category if category in KNOWN_CATEGORIES else "unclassified"
        super().__init__(f"Provider returned an error response: {self.category}")


class NonRetryableProviderError(ProviderResponseError):
    pass


def validate_research_provider_response(response):
    from .call_policy import active_policy

    if active_policy() is None:
        return
    category = provider_error_category(response)
    if category is not None:
        error_type = NonRetryableProviderError if category in NON_RETRYABLE_CATEGORIES else ProviderResponseError
        raise error_type(category)

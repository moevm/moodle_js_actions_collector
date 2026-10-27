from collections.abc import Callable
from inspect import signature
from typing import Any, TypeVar

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError


Model = TypeVar("Model", bound=BaseModel)


def query_model(model: type[Model]) -> Callable[..., Model]:
    """Preserve model query parameters and map its own validators to HTTP 422.

    FastAPI 0.110 validates individual parameters before calling dependencies,
    but a model dependency's cross-field/normalization errors otherwise escape
    as internal failures. Only validation of this request model is translated.
    """
    def parse(**values: Any) -> Model:
        try:
            return model.model_validate(values)
        except ValidationError as error:
            errors = [
                {**item, "loc": ("query", *item["loc"])}
                for item in error.errors(include_url=False, include_context=False, include_input=False)
            ]
            raise RequestValidationError(errors) from error

    # Reuse the Pydantic signature so OpenAPI and runtime validation stay aligned.
    setattr(parse, "__signature__", signature(model))
    return parse

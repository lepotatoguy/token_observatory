from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models.base import Model


Provider = Literal["claude", "codex", "minimax", "ollama", "lmstudio", "llamacpp"]
LocalProvider = Literal["ollama", "lmstudio", "llamacpp"]
Port = Annotated[int, Field(ge=1, le=65535)]


class Ports(Model):
    listen: Port
    target: Port

    @model_validator(mode="after")
    def different_ports(self):
        if self.listen == self.target:
            raise ValueError("listen and target ports must differ")
        return self


class ProviderSettings(Model):
    setup_done: bool
    enabled: dict[Provider, bool]
    ports: dict[LocalProvider, Ports]


class PortUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    listen: Port | None = None
    target: Port | None = None


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    setup_done: bool | None = None
    enabled: dict[Provider, bool] = Field(default_factory=dict)
    ports: dict[LocalProvider, PortUpdate] = Field(default_factory=dict)
    minimax: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("provider settings must not contain null values")
        return value


class ProviderStatus(Model):
    settings: ProviderSettings
    enabled: list[Provider]
    detected: dict[Provider, str | None]
    names: dict[Provider, str] = Field(default_factory=dict)
    cloud: list[Provider] = Field(default_factory=list)
    local: dict[str, Any] = Field(default_factory=dict)
    minimax: dict[str, Any] = Field(default_factory=dict)

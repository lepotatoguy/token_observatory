from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow", allow_inf_nan=False)

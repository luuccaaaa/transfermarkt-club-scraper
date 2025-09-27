from app.schemas.base import TransfermarktBaseModel


class ProxyStatus(TransfermarktBaseModel):
    enabled: bool
    count: int

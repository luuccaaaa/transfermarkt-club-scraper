from fastapi import APIRouter

from app.schemas.status import ProxyStatus
from app.utils.proxies import get_proxy_list


router = APIRouter()


@router.get("/proxies", response_model=ProxyStatus, response_model_exclude_none=True)
def get_proxy_status() -> ProxyStatus:
    proxies = get_proxy_list()
    return ProxyStatus(enabled=bool(proxies), count=len(proxies))
